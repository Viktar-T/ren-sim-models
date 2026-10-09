"""Plant boxes on the page: fields read from each params model, posted strings turned into plants.

No web code here. A box is posted as `p{i}.<field>` strings plus `p{i}.type` and `p{i}.shown_type`
(the type its fields were drawn for). Spec 0010. A box may also hold a datasheet imported from a
YAML file, carried in the hidden `p{i}.imported` (spec 0014).
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, get_args, get_origin

import yaml
from pydantic import ValidationError
from pydantic.fields import FieldInfo

from kiozesim import Plant
from kiozesim.datasheet import Datasheet
from kiozesim.plants import REGISTRY

# Plant types whose spec is implemented (UI-005).
OFFERED: tuple[str, ...] = ("pv", "hawt", "vawt")

# Drop-down value of a box's imported datasheet; no bundled name starts with ":" (IMP-003).
UPLOADED = ":uploaded"
MAX_IMPORT_BYTES = 100 * 1024  # IMP-008


@dataclass(frozen=True)
class Field:
    """One input on the page, described from a params model field (UI-006, UI-007, UI-008)."""

    name: str
    kind: Literal["number", "text", "select", "checkbox"]
    default: str = ""
    min: float | None = None
    max: float | None = None
    step: str = "any"
    choices: tuple[str, ...] = ()
    datasheet: bool = False  # the datasheet drop-down, which also lists the box's import


@dataclass
class Box:
    """One plant box: its type, the typed-in strings and an error message per field."""

    type: str
    values: dict[str, str]
    errors: dict[str, str] = field(default_factory=dict)  # "" = the box as a whole (UI-018)
    redrawn: bool = False  # type changed in this submit: fields reset, not simulated (UI-005)
    imported: str = ""  # YAML text of the box's imported datasheet (spec 0014)
    sheet: Datasheet | None = None  # that text, checked with the type's datasheet model

    @property
    def fields(self) -> list[Field]:
        return fields_of(self.type)

    @property
    def carried(self) -> str:
        """The import for the hidden field: base64, so browsers cannot rewrite its line breaks."""
        return base64.b64encode(self.imported.encode()).decode()

    def options(self, f: Field) -> list[tuple[str, str]]:
        """(value, label) per drop-down entry; the imported datasheet comes first (IMP-003)."""
        entries = [(c, c) for c in f.choices]
        if f.datasheet and self.sheet is not None:
            entries.insert(0, (UPLOADED, f"uploaded: {self.sheet.manufacturer} {self.sheet.model}"))
        return entries


def plant_class(plant_type: str) -> type[Plant]:  # type: ignore[type-arg]
    return REGISTRY[plant_type]


def _describe(name: str, info: FieldInfo) -> Field:
    ann = info.annotation
    default = "" if info.is_required() else str(info.default)
    if isinstance(ann, type) and issubclass(ann, Datasheet):
        return Field(name, "select", choices=tuple(ann.available()), datasheet=True)
    if ann is bool:  # posted as "true" when ticked, absent when not (UI-007)
        return Field(name, "checkbox", "true" if info.default else "false")
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


def sheet_model(plant_type: str) -> type[Datasheet] | None:
    """The datasheet model a plant type's params take, if any."""
    for info in plant_class(plant_type).params_model.model_fields.values():
        ann = info.annotation
        if isinstance(ann, type) and issubclass(ann, Datasheet):
            return ann
    return None


def read_sheet(plant_type: str, text: str) -> Datasheet:
    """A datasheet from YAML text, checked like the bundled files of that type (IMP-002).

    Raises ValueError saying what is wrong, with each field error as `field: message` (IMP-008).
    """
    model = sheet_model(plant_type)
    if model is None:
        raise ValueError(f"{plant_type} plants take no datasheet")
    try:
        data = yaml.safe_load(text)  # builds plain values only, never Python objects (IMP-009)
    except yaml.YAMLError as e:
        raise ValueError(f"not a YAML file: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("the file must hold `name: value` lines (a YAML mapping)")
    try:
        return model.model_validate(data)
    except ValidationError as e:
        messages = (_message(err["loc"], err["msg"]) for err in e.errors())
        raise ValueError("; ".join(messages)) from None


def _message(loc: tuple[int | str, ...], msg: str) -> str:
    return f"{'.'.join(str(p) for p in loc)}: {msg}" if loc else msg


def import_into(box: Box, content: bytes | None) -> None:
    """Load an uploaded file into the box, or write why not next to its file picker (IMP-008).

    `content` is None when no file was chosen. A failed import leaves an earlier one in place.
    """
    try:
        if content is None:
            raise ValueError("choose a file first")
        if len(content) > MAX_IMPORT_BYTES:
            raise ValueError(f"the file is larger than {MAX_IMPORT_BYTES // 1024} kB")
        try:
            text = content.decode("utf-8-sig")  # a leading byte-order mark is fine
        except UnicodeDecodeError:
            raise ValueError("not a text file") from None
        sheet = read_sheet(box.type, text)
    except ValueError as e:
        box.errors["upload"] = str(e)
        return
    box.imported, box.sheet = text, sheet
    box.errors.pop("upload", None)
    for f in box.fields:
        if f.datasheet:
            box.values[f.name] = UPLOADED


def _carry(box: Box, carried: str) -> None:
    """Take back the page's carried import, checked again like any posted value (IMP-005)."""
    try:
        text = base64.b64decode(carried, validate=True).decode()
        box.sheet = read_sheet(box.type, text)
    except ValueError as e:  # also bad base64 (binascii.Error) and bad UTF-8
        box.errors["upload"] = f"imported datasheet dropped: {e}"
        return
    box.imported = text


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
        else:  # a changed type drops the import with the other fields (IMP-006)
            box = Box(plant_type, {f.name: _posted(f, posted) for f in fields_of(plant_type)})
            if posted.get("imported"):
                _carry(box, posted["imported"])
        boxes.append(box)
    return boxes


def _posted(f: Field, posted: Mapping[str, str]) -> str:
    if f.kind == "checkbox":  # browsers send nothing for an unticked box
        return "true" if posted.get(f.name) else "false"
    return posted.get(f.name, "")


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
            if f.datasheet and raw == UPLOADED:  # the box's imported datasheet (IMP-007)
                if box.sheet is None:
                    box.errors[f.name] = "no imported datasheet; import a file first"
                else:
                    data[f.name] = box.sheet
            elif isinstance(ann, type) and issubclass(ann, Datasheet):
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
                key = str(err["loc"][0]) if err["loc"] else ""  # no field: whole box
                box.errors.setdefault(key, err["msg"])
            continue
        if not box.errors:
            plants.append(cls(params))
    if any(b.errors for b in boxes):
        return None
    return plants
