"""Plant and source boxes on the page: fields read from each params model, posted strings turned
into plants and sources.

No web code here. A plant box is posted as `p{i}.<field>` strings plus `p{i}.type` and
`p{i}.shown_type` (the type its fields were drawn for), its count as `n`. Spec 0010. A box may also
hold a datasheet imported from a YAML file, carried in the hidden `p{i}.imported` (spec 0014).
Source boxes are posted the same way as `s{i}.…` with count `ns`; every box's wiring is posted as
`<prefix>{i}.from.{j}` = source name, one per ticked source (spec 0016).
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import pandas as pd
import yaml
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from kiozesim import Plant, Source
from kiozesim.datasheet import Datasheet
from kiozesim_tool import boxes

Kind = Literal["plant", "source"]

# Plant types whose spec is implemented (UI-005), from the shared list (APP-005).
OFFERED: tuple[str, ...] = tuple(boxes.PLANTS)

SAMPLE_WEATHER = Path(__file__).resolve().parent / "sample_weather.csv"
# Source types on the page (SRC-040): the shared source type it is (APP-005) and the settings the
# page fixes (not shown as fields).
SOURCE_TYPES: dict[str, tuple[str, dict[str, Any]]] = {
    "sample weather": ("weather_file", {"path": SAMPLE_WEATHER}),  # SRC-041
    "online weather": ("open_meteo", {}),  # WX-040
    "constant": ("constant", {}),
    "digester": ("digester", {}),
}
SOURCES_OFFERED: tuple[str, ...] = tuple(SOURCE_TYPES)
PREFIX: dict[str, str] = {"plant": "p", "source": "s"}
COUNT: dict[str, str] = {"plant": "n", "source": "ns"}

# Drop-down value of a box's imported datasheet; no bundled name starts with ":" (IMP-003).
UPLOADED = ":uploaded"
MAX_IMPORT_BYTES = 100 * 1024  # IMP-008


@dataclass(frozen=True)
class Field:
    """One input on the page, described from a params model field (UI-006, UI-007, UI-008)."""

    name: str
    kind: Literal["number", "text", "select", "checkbox", "yaml"]
    default: str = ""
    min: float | None = None
    max: float | None = None
    step: str = "any"
    choices: tuple[str, ...] = ()
    datasheet: bool = False  # the datasheet drop-down, which also lists the box's import
    example: str = ""  # YAML fields: an example shown greyed out in the empty text area


@dataclass
class Box:
    """One box: its type, the typed-in strings and an error message per field."""

    type: str
    values: dict[str, str]
    kind: Kind = "plant"
    wired: list[str] = field(default_factory=list)  # names of the sources it takes input from
    errors: dict[str, str] = field(default_factory=dict)  # "" = the box as a whole (UI-018)
    redrawn: bool = False  # type changed in this submit: fields reset, not simulated (UI-005)
    imported: str = ""  # YAML text of the box's imported datasheet (spec 0014)
    sheet: Datasheet | None = None  # that text, checked with the type's datasheet model

    @property
    def fields(self) -> list[Field]:
        return fields_of(self.type, self.kind)

    @property
    def name(self) -> str:
        return self.values.get("name", "").strip()

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


def params_model(box_type: str, kind: Kind = "plant") -> type[BaseModel]:
    if kind == "source":
        return boxes.source_class(SOURCE_TYPES[box_type][0]).params_model
    return boxes.plant_class(box_type).params_model


def _describe(name: str, info: FieldInfo) -> Field:
    ann = info.annotation
    default = "" if info.is_required() else str(info.default)
    if isinstance(ann, type) and issubclass(ann, Datasheet):
        return Field(name, "select", choices=tuple(ann.available()), datasheet=True)
    if ann is bool:  # posted as "true" when ticked, absent when not (UI-007)
        return Field(name, "checkbox", "true" if info.default else "false")
    if get_origin(ann) is Literal:
        return Field(name, "select", default, choices=tuple(str(a) for a in get_args(ann)))
    if get_origin(ann) in (dict, list, tuple):  # nested settings, typed as YAML (SRC-042)
        example = yaml.safe_dump(info.examples[0], sort_keys=False) if info.examples else ""
        return Field(name, "yaml", default, example=example)
    if ann in (int, float):
        lo = hi = None
        for m in info.metadata:
            lo = getattr(m, "ge", None) if getattr(m, "ge", None) is not None else lo
            lo = getattr(m, "gt", None) if getattr(m, "gt", None) is not None else lo
            hi = getattr(m, "le", None) if getattr(m, "le", None) is not None else hi
            hi = getattr(m, "lt", None) if getattr(m, "lt", None) is not None else hi
        return Field(name, "number", default, lo, hi, "1" if ann is int else "any")
    return Field(name, "text", default)


def fields_of(box_type: str, kind: Kind = "plant") -> list[Field]:
    fixed = SOURCE_TYPES[box_type][1] if kind == "source" else {}
    model = params_model(box_type, kind)
    return [_describe(n, info) for n, info in model.model_fields.items() if n not in fixed]


def sheet_model(plant_type: str) -> type[Datasheet] | None:
    """The datasheet model a plant type's params take, if any."""
    return boxes.sheet_model(params_model(plant_type))


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


def unused_name(box_type: str, taken: set[str]) -> str:
    stem = box_type.replace(" ", "-")
    i = 1
    while f"{stem}-{i}" in taken:
        i += 1
    return f"{stem}-{i}"


def new_box(box_type: str, taken: set[str], kind: Kind = "plant") -> Box:
    values = {f.name: f.default for f in fields_of(box_type, kind)}
    values["name"] = unused_name(box_type, taken)
    return Box(box_type, values, kind)


def first_boxes() -> tuple[list[Box], list[Box]]:
    """The first page: one plant wired to one sample weather source (SRC-044)."""
    source = new_box(SOURCES_OFFERED[0], set(), "source")
    source.values["name"] = "weather"
    plant = new_box(OFFERED[0], {"weather"})
    plant.wired = ["weather"]
    return [plant], [source]


def read_boxes(form: Mapping[str, str], kind: Kind = "plant") -> list[Box]:
    """Boxes from a posted form. A box whose type changed gets the new type's defaults."""
    offered = OFFERED if kind == "plant" else SOURCES_OFFERED
    prefix = PREFIX[kind]
    n = int(form.get(COUNT[kind], "0"))
    found: list[Box] = []
    for i in range(n):
        posted = {
            k[len(f"{prefix}{i}.") :]: v for k, v in form.items() if k.startswith(f"{prefix}{i}.")
        }
        box_type = posted.get("type", "")
        box_type = box_type if box_type in offered else offered[0]
        if posted.get("shown_type") != box_type:
            box = new_box(box_type, {b.values["name"] for b in found}, kind)
            box.redrawn = True
        else:  # a changed type drops the import with the other fields (IMP-006)
            fields = fields_of(box_type, kind)
            box = Box(box_type, {f.name: _posted(f, posted) for f in fields}, kind)
            if posted.get("imported"):
                _carry(box, posted["imported"])
        box.wired = [v for k, v in sorted(posted.items()) if k.startswith("from.")]
        found.append(box)
    return found


def _posted(f: Field, posted: Mapping[str, str]) -> str:
    if f.kind == "checkbox":  # browsers send nothing for an unticked box
        return "true" if posted.get(f.name) else "false"
    return posted.get(f.name, "")


def _params(box: Box, seen: set[str]) -> BaseModel | None:
    """The box's params model, or None after writing every error into the box (UI-013)."""
    fixed = SOURCE_TYPES[box.type][1] if box.kind == "source" else {}
    model = params_model(box.type, box.kind)
    data: dict[str, Any] = dict(fixed)
    for f in box.fields:
        raw = box.values.get(f.name, "").strip()
        if raw == "":
            continue  # pydantic reports a missing required field
        if f.datasheet and raw == UPLOADED:  # the box's imported datasheet (IMP-007)
            if box.sheet is None:
                box.errors[f.name] = "no imported datasheet; import a file first"
            else:
                data[f.name] = box.sheet
        elif f.kind == "yaml":  # builds plain values only, never Python objects (SRC-042)
            try:
                data[f.name] = yaml.safe_load(raw)
            except yaml.YAMLError as e:
                box.errors[f.name] = f"not YAML: {e}"
        else:
            data[f.name] = raw
    data, errors = boxes.resolve(model, data)  # a datasheet by name: the bundled one
    for key, msg in errors.items():
        box.errors.setdefault(key, msg)
    name = box.name
    if name and name in seen:
        box.errors["name"] = f"name {name!r} is already used by another box"
    seen.add(name)
    try:
        params = model.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            key = str(err["loc"][0]) if err["loc"] else ""  # no field: whole box
            msg = err["msg"] if len(err["loc"]) < 2 else _message(err["loc"][1:], err["msg"])
            box.errors.setdefault(key, msg)
        return None
    return None if box.errors else params


def build(
    plant_boxes: list[Box], source_boxes: list[Box]
) -> tuple[list[Plant], list[Source]] | None:  # type: ignore[type-arg]
    """Plants and sources from boxes, or None after writing every error into its box (UI-013)."""
    seen: set[str] = set()
    plants: list[Plant] = []  # type: ignore[type-arg]
    sources: list[Source] = []  # type: ignore[type-arg]
    for box in source_boxes:
        params = _params(box, seen)
        if params is not None:
            try:
                sources.append(boxes.source_class(SOURCE_TYPES[box.type][0])(params))
            except ValueError as e:  # e.g. a weather file that does not read
                box.errors[""] = str(e)
    for box in plant_boxes:
        params = _params(box, seen)
        if params is not None:
            plants.append(boxes.plant_class(box.type)(params))
    if any(b.errors for b in [*plant_boxes, *source_boxes]):
        return None
    return plants, sources


# The run period beside the Run button (WX-041).
DEFAULT_FROM = "2026-06-21"
MAX_DAYS = 31


@dataclass
class Period:
    """The typed-in run period: a first date and a number of days, hourly, UTC."""

    start: str = DEFAULT_FROM
    days: str = "1"
    errors: dict[str, str] = field(default_factory=dict)  # by field: "run_from", "run_days"

    @classmethod
    def read(cls, form: Mapping[str, str]) -> Period:
        return cls(form.get("run_from", DEFAULT_FROM), form.get("run_days", "1"))

    def index(self) -> pd.DatetimeIndex | None:
        """The hourly run index, or None after writing every error into `errors`."""
        start = days = None
        try:
            start = pd.Timestamp(self.start.strip())
            if start != start.normalize() or start.tz is not None:
                raise ValueError
        except ValueError:
            self.errors["run_from"] = "a date like 2026-06-21"
        try:
            days = int(self.days.strip())
            if not 1 <= days <= MAX_DAYS:
                raise ValueError
        except ValueError:
            self.errors["run_days"] = f"a whole number from 1 to {MAX_DAYS}"
        if start is None or days is None or self.errors:
            return None
        return pd.date_range(start.tz_localize("UTC"), periods=24 * days, freq="h")
