"""Wiring sources and plants: the apps' job, shared here (specs 0016 SRC-020..024, 0019 CHAIN-040).

Every plant that takes input names what it takes input from: sources, and at most one plant in
front of it. A source may name sources. The output tables of a box's sources are joined side by
side and handed to it. Plants wired to plants form straight chains, each run by the library's
`Chain` (requests back, supplies forward); a plant on its own is a chain of one.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from kiozesim import Chain, MissingInputError, Plant
from kiozesim.plants.base import State
from kiozesim_tool.sources import Source

Wires = Mapping[str, Sequence[str]]  # box name -> names of the boxes it takes input from


class WiringError(ValueError):
    """Wrong wiring; `box` names the box the message belongs to."""

    def __init__(self, box: str, message: str) -> None:
        self.box = box
        super().__init__(f"{box}: {message}")


@dataclass(frozen=True)
class RunResult:
    power: pd.DataFrame  # power_kw per plant plus `total` (CHAIN-041)
    outputs: dict[str, pd.DataFrame]  # every plant's outputs
    states: dict[str, State]  # every plant's state after the last step, to continue from


def check(
    source_names: Sequence[str],
    plant_names: Sequence[str],
    wires: Wires,
    no_input: Collection[str] = (),
) -> list[str]:
    """Source names in run order, after rejecting bad wiring (SRC-020, CHAIN-040).

    `no_input`: plants that take no input and so need no wire (e.g. a digester).
    """
    seen: set[str] = set()
    for name in [*source_names, *plant_names]:
        if name in seen:
            raise WiringError(name, "name is used by more than one box")
        seen.add(name)
    sources, plants = set(source_names), set(plant_names)
    for name in [*source_names, *plant_names]:
        froms = list(wires.get(name, ()))
        if name in plants and not froms and name not in no_input:
            raise WiringError(name, "not wired to any source")
        if name in plants and froms and name in no_input:
            raise WiringError(name, "takes no input, so it is wired to nothing")
        for f in froms:
            if name in sources and f not in sources:
                raise WiringError(name, f"wired to {f!r}, which is not a source")
            if name in plants and f not in sources | plants:
                raise WiringError(name, f"wired to {f!r}, which is not a source or a plant")
        if len(set(froms)) != len(froms):
            raise WiringError(name, "wired to the same box twice")
    feeds: dict[str, list[str]] = {}
    for name in plant_names:
        fronts = [f for f in wires.get(name, ()) if f in plants]
        if len(fronts) > 1:
            raise WiringError(name, f"takes input from two plants ({', '.join(fronts)})")
        for f in fronts:
            feeds.setdefault(f, []).append(name)
    for name, behind in feeds.items():
        if len(behind) > 1:
            raise WiringError(name, f"feeds two plants ({', '.join(behind)})")
    order: list[str] = []
    state: dict[str, str] = {}  # "busy" while what it is wired to is visited, then "done"

    def visit(name: str, path: list[str]) -> None:
        if state.get(name) == "done":
            return
        if state.get(name) == "busy":
            loop = path[path.index(name) :] + [name]
            raise WiringError(name, f"wiring loop {' -> '.join(loop)}")
        state[name] = "busy"
        for f in wires.get(name, ()):
            visit(f, [*path, name])
        state[name] = "done"
        if name in sources:
            order.append(name)

    for name in [*source_names, *plant_names]:
        visit(name, [])
    return order


def chains(plant_names: Sequence[str], wires: Wires) -> list[list[str]]:
    """Plants grouped into straight chains, front to back, after `check`."""
    plants = set(plant_names)
    front_of = {n: next((f for f in wires.get(n, ()) if f in plants), None) for n in plant_names}
    behind = {f: n for n, f in front_of.items() if f is not None}
    found = []
    for name in plant_names:
        if front_of[name] is None:
            chain = [name]
            while chain[-1] in behind:
                chain.append(behind[chain[-1]])
            found.append(chain)
    return found


def chain_to(plant: str, plant_names: Sequence[str], wires: Wires) -> list[str]:
    """The chain from its front up to and including `plant`."""
    for chain in chains(plant_names, wires):
        if plant in chain:
            return chain[: chain.index(plant) + 1]
    raise WiringError(plant, "no such plant")


def join(box: str, tables: Mapping[str, pd.DataFrame]) -> pd.DataFrame | None:
    """The tables of a box's sources side by side; one column from two sources: error (SRC-024)."""
    if not tables:
        return None
    owner: dict[str, str] = {}
    for src, table in tables.items():
        for col in map(str, table.columns):
            if col in owner:
                raise WiringError(box, f"column {col!r} comes from both {owner[col]} and {src}")
            owner[col] = src
    return pd.concat(list(tables.values()), axis=1)


def _missing(box: str, froms: Sequence[str], e: MissingInputError) -> WiringError:
    where = ", ".join(froms) if froms else "no source"
    return WiringError(box, f"wired to {where}, which give no {', '.join(e.missing)}")


def no_input(plants: Sequence[Plant]) -> set[str]:  # type: ignore[type-arg]
    return {p.name for p in plants if p.inputs_model is None}


def run(
    sources: Sequence[Source],  # type: ignore[type-arg]
    plants: Sequence[Plant],  # type: ignore[type-arg]
    wires: Wires,
    index: pd.DatetimeIndex,
    states: Mapping[str, State] | None = None,
) -> RunResult:
    """Run each source once, in wiring order, then every chain of plants (SRC-021, CHAIN-040).

    `states` continues plants with memory from an earlier run (e.g. the day before).
    """
    by_name = {s.name: s for s in sources}
    plant_names = [p.name for p in plants]
    order = check(list(by_name), plant_names, wires, no_input(plants))
    tables: dict[str, pd.DataFrame] = {}
    for name in order:
        froms = list(wires.get(name, ()))
        inputs = join(name, {f: tables[f] for f in froms})
        try:
            tables[name] = by_name[name].simulate(index, inputs)
        except MissingInputError as e:
            raise _missing(name, froms, e) from None
    plant_by_name = {p.name: p for p in plants}
    outputs: dict[str, pd.DataFrame] = {}
    end_states: dict[str, State] = {}
    for names in chains(plant_names, wires):
        fed: dict[str, pd.DataFrame] = {}  # per plant, its sources' tables joined
        for name in names:
            frame = join(name, {f: tables[f] for f in wires.get(name, ()) if f in tables})
            if frame is not None:
                fed[name] = frame
        try:
            res = Chain([plant_by_name[n] for n in names]).run(index, fed, states)
        except MissingInputError as e:
            raise _missing(e.box, list(wires.get(e.box, ())), e) from None
        outputs |= res.outputs
        end_states |= res.states
    power = pd.DataFrame({n: outputs[n]["power_kw"] for n in plant_names}, index=index)
    power["total"] = power.sum(axis=1)
    return RunResult(power, outputs, end_states)
