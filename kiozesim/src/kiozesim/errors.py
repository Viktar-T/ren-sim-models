"""Errors shared by plants, chains and the tool's sources."""

from __future__ import annotations


class MissingInputError(ValueError):
    """A box was handed an input table without columns it needs (spec 0016, SRC-002/003).

    Apps catch it to say the box was wired to the wrong source.
    """

    def __init__(self, box: str, missing: list[str] | tuple[str, ...]) -> None:
        self.box = box
        self.missing = tuple(missing)
        super().__init__(f"{box}: missing input column(s) {', '.join(self.missing)}")


class CannotBeAsked(ValueError):
    """Sizing asked a plant for more than it can be asked for, e.g. PV for sunshine (CHAIN-024)."""

    def __init__(self, plant: str, why: str = "driven by weather, it cannot be asked") -> None:
        self.plant = plant
        super().__init__(f"{plant}: {why}")
