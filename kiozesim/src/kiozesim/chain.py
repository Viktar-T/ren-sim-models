"""Plant chains: plants in a row, front to back. Spec 0019.

How plants connect: only `FLOWS` (fuel, heat, electricity) pass from a plant to the plant behind
it, matched by name. Everything else a plant needs (weather, heat demand) comes from the caller's
table for that plant.

How a chain runs (`Chain.run`): plants up to the last one with memory (a tank) go one time step at
a time, because what they do depends on each other. Each step has two passes:
  1. requests, back to front: each plant tells the one in front what it wants (`Plant.want`);
  2. supplies, front to back: each plant makes what it can and hands it on (`Plant.step`).
Plants behind the last one with memory hear no requests, so they run all at once (`simulate`).

Sizing (`Chain.size`) walks back to front on averages: what each plant needs (`Plant.needs`).

The library never fetches or reads anything here: the caller hands in the tables.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from kiozesim.errors import CannotBeAsked, MissingInputError
from kiozesim.plants.base import Plant, PlantOutput, State
from kiozesim.timegrid import TimeGridError, validate_time_index

FLOWS = ("fuel_kw", "heat_kw", "power_kw")  # what flows from plant to plant (naming scheme)
_TOL = 1e-9

Values = dict[str, float]  # one step's values, by name


@dataclass(frozen=True)
class ChainResult:
    outputs: dict[str, pd.DataFrame]  # every plant's outputs, per plant name, on the run index
    flared_kw: pd.Series  # fuel_kw the last plant leaves
    states: dict[str, State]  # every plant's state after the last step


@dataclass(frozen=True)
class SizingStep:
    plant: str
    wanted: dict[str, float]  # average output asked of it
    given: dict[str, float]  # what it can give
    needs: dict[str, float]  # average inputs it needs for that
    feed_t_per_day: dict[str, float] = field(default_factory=dict)  # digester: feed per substrate

    @property
    def shortfall(self) -> dict[str, float]:
        """Wanted but not given, per output."""
        gap = {k: v - self.given.get(k, 0.0) for k, v in self.wanted.items()}
        return {k: v for k, v in gap.items() if v > _TOL * max(1.0, abs(self.wanted[k]))}


@dataclass(frozen=True)
class SizingResult:
    steps: list[SizingStep]  # back to front
    stopped_at: str | None = None  # a plant that cannot be asked, where the walk stopped
    reason: str = ""


@dataclass(frozen=True)
class _Link:
    """One plant in a run, and where its inputs come from."""

    name: str
    plant: Plant  # type: ignore[type-arg]
    piped: list[str]  # inputs that come through the pipe from the plant in front
    own: pd.DataFrame  # its other inputs, from the caller's table

    def own_values_per_step(self) -> list[Values]:
        """Its own inputs as one small dict per time step, e.g. [{"heat_demand_kw": 150.0}, ...]."""
        columns: dict[str, list[float]] = {}
        for column in self.own.columns:
            columns[str(column)] = self.own[column].astype(float).tolist()  # one pandas call each

        steps: list[Values] = []
        for k in range(len(self.own.index)):
            values: Values = {}
            for name, column_values in columns.items():
                values[name] = column_values[k]
            steps.append(values)
        return steps

    def all_inputs(self, front_outputs: pd.DataFrame | None) -> pd.DataFrame:
        """Its whole input table: its own columns plus the piped columns from the front."""
        if front_outputs is None or not self.piped:
            return self.own
        piped_columns = front_outputs[self.piped]
        return self.own.join(piped_columns)


def _only(values: Mapping[str, float], names: list[str]) -> Values:
    """The entries of `values` whose name is in `names`."""
    picked: Values = {}
    for name, value in values.items():
        if name in names:
            picked[name] = value
    return picked


class Chain:
    """A straight chain of plants, front to back."""

    def __init__(self, plants: Sequence[Plant]) -> None:  # type: ignore[type-arg]
        if not plants:
            raise ValueError("a chain needs at least one plant")
        names = [p.name for p in plants]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"plant names in a chain must be unique: {', '.join(duplicates)}")
        self.plants = list(plants)

    @property
    def names(self) -> list[str]:
        return [p.name for p in self.plants]

    def _plant_in_front_of(self, i: int) -> Plant | None:  # type: ignore[type-arg]
        if i == 0:
            return None
        return self.plants[i - 1]

    # --- running ---------------------------------------------------------------------------

    def run(
        self,
        index: pd.DatetimeIndex,
        inputs: Mapping[str, pd.DataFrame] | None = None,
        states: Mapping[str, State] | None = None,
    ) -> ChainResult:
        """Run the chain on `index`.

        `inputs`: per plant name, its columns from the caller (sources) on `index`.
        `states`: per plant name, the memory to start from (default: `initial_state`).
        """
        validate_time_index(index)
        links = self._links(index, inputs or {})
        memory = self._starting_memory(states or {})

        # Three zones, front to back. Only the middle one needs to go step by step:
        #   front:  plants that ignore requests and have no memory (a digester): all at once
        #   middle: up to the last plant with memory (a tank): step by step, requests and supplies
        #   back:   plants behind the last one with memory, nobody asks them anything: all at once
        n_front = self._count_front_at_once()
        n_stepped = self._count_stepped()
        front_links = links[:n_front]
        middle_links = links[n_front:n_stepped]
        back_links = links[n_stepped:]

        outputs: dict[str, pd.DataFrame] = {}
        front_outputs: pd.DataFrame | None = None
        for link in front_links:
            front_outputs = self._run_at_once(link, front_outputs, index)
            outputs[link.name] = front_outputs
        if middle_links:
            middle_outputs = self._run_stepped(middle_links, front_outputs, index, memory)
            outputs.update(middle_outputs)
            front_outputs = middle_outputs[middle_links[-1].name]
        for link in back_links:
            front_outputs = self._run_at_once(link, front_outputs, index)
            outputs[link.name] = front_outputs

        return ChainResult(outputs, self._flared(outputs, index), memory)

    def _starting_memory(self, states: Mapping[str, State]) -> dict[str, State]:
        memory: dict[str, State] = {}
        for plant in self.plants:
            if plant.name in states:
                memory[plant.name] = states[plant.name]
            else:
                memory[plant.name] = plant.initial_state()
        return memory

    def _count_front_at_once(self) -> int:
        """How many plants at the front ignore requests and have no memory (CHAIN-012).

        Nothing behind them changes what they make, so they can run all at once. Only plants in
        front of the last plant with memory count; the ones behind it run all at once anyway.
        """
        count = 0
        for plant in self.plants[: self._count_stepped()]:
            if plant.follows_requests or plant.initial_state() is not None:
                break
            count += 1
        return count

    def _count_stepped(self) -> int:
        """How many plants, from the front, must go step by step: up to the last with memory."""
        count = 0
        for i, plant in enumerate(self.plants):
            if plant.initial_state() is not None:
                count = i + 1
        return count

    def _flared(self, outputs: Mapping[str, pd.DataFrame], index: pd.DatetimeIndex) -> pd.Series:
        """The fuel the last plant leaves: nobody behind it can burn it."""
        last = outputs[self.names[-1]]
        if "fuel_kw" in last.columns:
            flared = last["fuel_kw"].astype(float)
        else:
            flared = pd.Series(0.0, index=index)
        return flared.rename("flared_kw")

    def _links(self, index: pd.DatetimeIndex, inputs: Mapping[str, pd.DataFrame]) -> list[_Link]:
        """Where each plant's inputs come from; MissingInputError if one is missing (CHAIN-010)."""
        links: list[_Link] = []
        for i, plant in enumerate(self.plants):
            front = self._plant_in_front_of(i)
            table = inputs.get(plant.name, pd.DataFrame(index=index))
            if not table.index.equals(index):
                raise TimeGridError(f"{plant.name}: inputs are not on the requested time axis")

            # inputs that come through the pipe: flows the plant in front gives
            piped: list[str] = []
            if front is not None:
                for name in plant.input_names():
                    if name in FLOWS and name in front.output_names():
                        piped.append(name)

            # inputs from the caller; behind the first plant, flows only ever come from the front
            from_caller: list[str] = []
            for column in table.columns:
                name = str(column)
                if name not in plant.input_names():
                    continue
                if front is not None and name in FLOWS:
                    continue
                from_caller.append(name)

            missing = []
            for name in plant.required_inputs():
                if name not in piped and name not in from_caller:
                    missing.append(name)
            if missing:
                raise MissingInputError(plant.name, missing)

            links.append(_Link(plant.name, plant, piped, table[from_caller]))
        return links

    def _run_at_once(
        self, link: _Link, front_outputs: pd.DataFrame | None, index: pd.DatetimeIndex
    ) -> pd.DataFrame:
        """The plant's whole run in one `simulate` call."""
        plant = link.plant
        if plant.inputs_model is None:
            out: PlantOutput = plant.simulate()
        else:
            plant_inputs = plant.inputs_model.from_frame(link.all_inputs(front_outputs))
            out = plant.simulate(plant_inputs)
        return out.to_frame(index)

    def _run_stepped(
        self,
        links: list[_Link],
        front_outputs: pd.DataFrame | None,
        index: pd.DatetimeIndex,
        memory: dict[str, State],
    ) -> dict[str, pd.DataFrame]:
        """These plants, one time step at a time (CHAIN-011). Updates `memory` in place.

        `front_outputs`: what the plant in front of the first one made, if it ran all at once.
        """
        dt_h = (index[1] - index[0]) / pd.Timedelta(hours=1)
        first = links[0]
        if front_outputs is not None and first.piped:
            # the plant in front already ran: its piped columns become this plant's own inputs
            first = _Link(first.name, first.plant, [], first.all_inputs(front_outputs))
            links = [first, *links[1:]]

        own_per_step: dict[str, list[Values]] = {}
        made_per_step: dict[str, list[Values]] = {}
        for link in links:
            own_per_step[link.name] = link.own_values_per_step()
            made_per_step[link.name] = []

        for k, t in enumerate(index):
            own: dict[str, Values] = {}
            for link in links:
                own[link.name] = own_per_step[link.name][k]

            wanted = self._requests(links, t, dt_h, own, memory)
            made = self._supplies(links, t, dt_h, own, memory, wanted)

            for link in links:
                made_per_step[link.name].append(made[link.name])

        outputs: dict[str, pd.DataFrame] = {}
        for link in links:
            outputs[link.name] = pd.DataFrame(made_per_step[link.name], index=index, dtype=float)
        return outputs

    def _requests(
        self,
        links: list[_Link],
        t: pd.Timestamp,
        dt_h: float,
        own: Mapping[str, Values],
        memory: Mapping[str, State],
    ) -> dict[str, Values]:
        """Pass 1, back to front: what each plant is asked for by the plant behind it."""
        wanted: dict[str, Values] = {}
        wanted[links[-1].name] = {}  # nobody is behind the last plant

        # walk from the last plant to the second; each one asks the plant in front of it
        for i in range(len(links) - 1, 0, -1):
            behind = links[i]
            front = links[i - 1]
            asked = behind.plant.want(
                memory[behind.name], t, own[behind.name], wanted[behind.name], dt_h
            )
            wanted[front.name] = _only(asked, behind.piped)
        return wanted

    def _supplies(
        self,
        links: list[_Link],
        t: pd.Timestamp,
        dt_h: float,
        own: Mapping[str, Values],
        memory: dict[str, State],
        wanted: Mapping[str, Values],
    ) -> dict[str, Values]:
        """Pass 2, front to back: each plant makes what it can and hands it on."""
        made: dict[str, Values] = {}
        front_made: Values = {}  # what the plant in front just made; nothing before the first
        for link in links:
            inputs = dict(own[link.name])
            inputs.update(_only(front_made, link.piped))

            new_memory, outputs = link.plant.step(
                memory[link.name], t, inputs, wanted[link.name], dt_h
            )
            memory[link.name] = new_memory
            made[link.name] = outputs
            front_made = outputs
        return made

    # --- sizing ----------------------------------------------------------------------------

    def size(self, wanted: Mapping[str, float]) -> SizingResult:
        """Walk back to front: what each plant needs, on average, for `wanted` from the last."""
        last = self.plants[-1]
        if last.askable:  # a plant that cannot be asked at all stops the walk below
            last.check_asked(wanted)

        steps: list[SizingStep] = []
        asked = dict(wanted)
        for i in range(len(self.plants) - 1, -1, -1):
            plant = self.plants[i]
            try:
                sizing = plant.needs(asked)
            except CannotBeAsked as e:
                return SizingResult(steps, plant.name, str(e))
            steps.append(
                SizingStep(plant.name, asked, sizing.given, sizing.inputs, sizing.feed_t_per_day)
            )

            front = self._plant_in_front_of(i)
            if front is None:
                break
            # what this plant needs through the pipe is what the plant in front is asked for
            asked = {}
            for name, kw in sizing.inputs.items():
                if name in FLOWS and name in front.output_names():
                    asked[name] = kw
            if not asked:
                break
        return SizingResult(steps)
