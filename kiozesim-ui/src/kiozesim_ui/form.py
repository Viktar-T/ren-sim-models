"""Plant boxes on the page: fields read from each params model, posted strings turned into plants.

No web code here. A box is posted as `p{i}.<field>` strings plus `p{i}.type` and `p{i}.shown_type`
(the type its fields were drawn for). Spec 0010.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, get_args, get_origin

from pydantic import ValidationError
from pydantic.fields import FieldInfo

from kiozesim import Plant
from kiozesim.datasheet import Datasheet
from kiozesim.plants import REGISTRY

# Plant types whose spec is implemented (UI-005).
OFFERED: tuple[str, ...] = ("pv",)


@dataclass(frozen=True)
class Field:
    """One input on the page, described from a params model field (UI-006, UI-007, UI-008)."""

    name: str
    kind: Literal["number", "text", "select"]
    default: str = ""
    min: float | None = None
    max: float | None = None
    step: str = "any"
    choices: tuple[str, ...] = ()


@dataclass
class Box:
    """One plant box: its type, the typed-in strings and an error message per field."""

    type: str
    values: dict[str, str]
    errors: dict[str, str] = field(default_factory=dict)
    redrawn: bool = False  # type changed in this submit: fields reset, not simulated (UI-005)

    @property
    def fields(self) -> list[Field]:
        return fields_of(self.type)


def plant_class(plant_type: str) -> type[Plant]:  # type: ignore[type-arg]
    return REGISTRY[plant_type]


def _describe(name: str, info: FieldInfo) -> Field:
    ann = info.annotation
    default = "" if info.is_required() else str(info.default)
    if isinstance(ann, type) and issubclass(ann, Datasheet):
        return Field(name, "select", choices=tuple(ann.available()))
    if get_origin(ann) is Literal:
        return Field(name, "select", default, choices=tuple(str(a) for a in get_args(ann)))
    if ann in (int, float):
        lo = hi = None
        for m in info.metadata:
            lo = getattr(m, "ge", None) if getattr(m, "ge", None) is not None else lo
            lo = getattr(m, "gt", None) if getattr(m, "gt", None) is not None else lo
            hi = getattr(m, "le", None) if getattr(m, "le", None) is not None else hi
            hi = getattr(m, "lt", None) if getattr(m, "lt", None) is not None else hi
        return Field(name, "number", default, lo, hi, "1" if ann is int else "any")
    return Field(name, "text", default)


def fields_of(plant_type: str) -> list[Field]:
    model = plant_class(plant_type).params_model
    return [_describe(n, info) for n, info in model.model_fields.items()]


def unused_name(plant_type: str, taken: set[str]) -> str:
    i = 1
    while f"{plant_type}-{i}" in taken:
        i += 1
    return f"{plant_type}-{i}"


def new_box(plant_type: str, taken: set[str]) -> Box:
    values = {f.name: f.default for f in fields_of(plant_type)}
    values["name"] = unused_name(plant_type, taken)
    return Box(plant_type, values)


def read_boxes(form: Mapping[str, str]) -> list[Box]:
    """Boxes from a posted form. A box whose type changed gets the new type's defaults."""
    n = int(form.get("n", "0"))
    boxes: list[Box] = []
    for i in range(n):
        posted = {k[len(f"p{i}.") :]: v for k, v in form.items() if k.startswith(f"p{i}.")}
        plant_type = posted.get("type", "")
        plant_type = plant_type if plant_type in OFFERED else OFFERED[0]
        if posted.get("shown_type") != plant_type:
            box = new_box(plant_type, {b.values["name"] for b in boxes})
            box.redrawn = True
        else:
            box = Box(plant_type, {f.name: posted.get(f.name, "") for f in fields_of(plant_type)})
        boxes.append(box)
    return boxes


def build_plants(boxes: list[Box]) -> list[Plant] | None:  # type: ignore[type-arg]
    """Plants from boxes, or None after writing every error into its box (UI-013)."""
    plants: list[Plant] = []  # type: ignore[type-arg]
    seen: set[str] = set()
    for box in boxes:
        cls = plant_class(box.type)
        data: dict[str, Any] = {}
        for f in box.fields:
            raw = box.values.get(f.name, "").strip()
            if raw == "":
                continue  # pydantic reports a missing required field
            ann = cls.params_model.model_fields[f.name].annotation
            if isinstance(ann, type) and issubclass(ann, Datasheet):
                try:
                    data[f.name] = ann.bundled(raw)
                except FileNotFoundError:
                    box.errors[f.name] = f"no bundled datasheet {raw!r}"
            else:
                data[f.name] = raw
        name = box.values.get("name", "").strip()
        if name and name in seen:
            box.errors["name"] = f"name {name!r} is already used by another plant"
        seen.add(name)
        try:
            params = cls.params_model.model_validate(data)
        except ValidationError as e:
            for err in e.errors():
                key = str(err["loc"][0]) if err["loc"] else "name"
                box.errors.setdefault(key, err["msg"])
            continue
        if not box.errors:
            plants.append(cls(params))
    if any(b.errors for b in boxes):
        return None
    return plants
