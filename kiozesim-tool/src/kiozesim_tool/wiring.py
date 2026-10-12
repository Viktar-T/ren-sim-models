"""Wiring sources to plants: the apps' job, shared here (spec 0016, SRC-020..024).

Every plant names the sources it takes input from; a source may too. The output tables of a box's
sources are joined side by side and handed to it. The library's boxes only check that the columns
they need are there.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from kiozesim import MissingInputError, Plant, Portfolio, Source, TimeSeries

Wires = Mapping[str, Sequence[str]]  # box name -> names of the sources it is wired to


class WiringError(ValueError):
    """Wrong wiring; `box` names the box the message belongs to."""

    def __init__(self, box: str, message: str) -> None:
        self.box = box
        super().__init__(f"{box}: {message}")


def check(source_names: Sequence[str], plant_names: Sequence[str], wires: Wires) -> list[str]:
    """Source names in run order, after rejecting bad wiring (SRC-020)."""
    seen: set[str] = set()
    for name in [*source_names, *plant_names]:
        if name in seen:
            raise WiringError(name, "name is used by more than one box")
        seen.add(name)
    sources = set(source_names)
    for name in [*source_names, *plant_names]:
        froms = list(wires.get(name, ()))
        if name in plant_names and not froms:
            raise WiringError(name, "not wired to any source")
        for f in froms:
            if f not in sources:
                raise WiringError(name, f"wired to {f!r}, which is not a source")
        if len(set(froms)) != len(froms):
            raise WiringError(name, "wired to the same source twice")
    order: list[str] = []
    state: dict[str, str] = {}  # "busy" while its sources are visited, then "done"

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
        order.append(name)

    for name in source_names:
        visit(name, [])
    return order


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


def run(
    sources: Sequence[Source],  # type: ignore[type-arg]
    plants: Sequence[Plant],  # type: ignore[type-arg]
    wires: Wires,
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Run each source once, in wiring order, then the plants as one `Portfolio` (SRC-021)."""
    by_name = {s.name: s for s in sources}
    order = check(list(by_name), [p.name for p in plants], wires)
    tables: dict[str, pd.DataFrame] = {}
    for name in order:
        froms = list(wires.get(name, ()))
        inputs = join(name, {f: tables[f] for f in froms})
        try:
            tables[name] = by_name[name].simulate(index, inputs)
        except MissingInputError as e:
            raise _missing(name, froms, e) from None
    plant_inputs: dict[str, TimeSeries] = {}
    for p in plants:
        froms = list(wires[p.name])
        frame = join(p.name, {f: tables[f] for f in froms})
        if p.inputs_model is not None and frame is not None:
            try:
                plant_inputs[p.name] = p.inputs_model.from_frame(frame)
            except MissingInputError as e:
                raise _missing(p.name, froms, e) from None
    return Portfolio(list(plants)).simulate(plant_inputs)
