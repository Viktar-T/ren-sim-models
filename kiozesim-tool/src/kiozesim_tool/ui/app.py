"""The web server: one server-rendered page, every button a plain form post (spec 0010)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.datastructures import UploadFile

from kiozesim import SizingResult
from kiozesim_tool import sizing, wiring
from kiozesim_tool.ui import form
from kiozesim_tool.ui.chart import output_svgs, power_svg

HERE = Path(__file__).resolve().parent

app = FastAPI(title="kiozesim")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
# Changes with the stylesheet's content, so browsers fetch a changed file instead of a cached one.
CSS_VERSION = hashlib.sha256((HERE / "static" / "style.css").read_bytes()).hexdigest()[:12]


@dataclass(frozen=True)
class Result:
    energy_kwh: dict[str, float]  # per plant plus "total"
    chart: Markup  # power (UI-015)
    output_charts: list[tuple[str, Markup]]  # (field, chart) for every other output (PLOT-001)


def simulate(
    plant_boxes: list[form.Box], source_boxes: list[form.Box], period: form.Period
) -> tuple[Result | None, str]:
    """Run all plants as one portfolio, fed by their wired sources. Returns (result, page error)."""
    index = period.index()  # WX-041; the sample weather repeats its day on each date (UI-011)
    built = form.build(plant_boxes, source_boxes)
    if built is None or index is None:
        return None, ""
    plants, sources = built
    wires = {b.name: b.wired for b in [*plant_boxes, *source_boxes]}
    try:
        run = wiring.run(sources, plants, wires, index)
    except (ValueError, TypeError, ImportError) as e:
        # wiring and weather errors are shown on the box they belong to (SRC-022, WX-042)
        for b in [*plant_boxes, *source_boxes]:
            if b.name == getattr(e, "box", None):
                b.errors[""] = str(e)
                return None, ""
        return None, str(e)
    power = run.power
    step_h = (power.index[1] - power.index[0]) / pd.Timedelta(hours=1)
    energy = {str(c): float(power[c].sum() * step_h) for c in power.columns}
    # per plant in the order of the boxes (PLOT-002)
    outputs = {p.name: run.outputs[p.name] for p in plants}
    charts = [(field, Markup(svg)) for field, svg in output_svgs(outputs)]
    return Result(energy, Markup(power_svg(power)), charts), ""


@dataclass(frozen=True)
class SizingRow:
    plant: str
    wanted: str
    given: str
    short: str
    needs: str
    feed: str


def size(
    plant_boxes: list[form.Box], source_boxes: list[form.Box], request: form.Sizing
) -> list[SizingRow] | None:
    """Size the chain ending at the chosen plant (CHAIN-043); errors go into boxes or request."""
    wanted = None
    try:
        wanted = sizing.parse_want([request.want])
    except ValueError as e:
        request.errors["size_want"] = str(e)
    built = form.build(plant_boxes, source_boxes)
    if built is None or wanted is None:
        return None
    plants, sources = built
    wires = {b.name: b.wired for b in [*plant_boxes, *source_boxes]}
    try:
        res: SizingResult = sizing.size(plants, sources, wires, request.plant, wanted)
    except ValueError as e:
        for b in [*plant_boxes, *source_boxes]:
            if b.name == getattr(e, "box", None):
                b.errors[""] = str(e)
                return None
        request.errors["size_want"] = str(e)
        return None
    rows = [
        SizingRow(
            s.plant,
            sizing.kw(s.wanted),
            sizing.kw(s.given),
            sizing.kw(s.shortfall) if s.shortfall else "",
            sizing.kw(s.needs) if s.needs else "",
            sizing.feed(s.feed_t_per_day),
        )
        for s in res.steps
    ]
    if res.stopped_at is not None:
        rows.append(SizingRow(res.stopped_at, "", "", "", "", res.reason))
    return rows


def page(  # type: ignore[no-untyped-def]
    request: Request,
    plants: list[form.Box],
    sources: list[form.Box],
    period: form.Period,
    result: Result | None = None,
    error: str = "",
    sizing_request: form.Sizing | None = None,
    sizing_rows: list[SizingRow] | None = None,
):
    return templates.TemplateResponse(
        request,
        "page.html",
        {
            "plants": plants,
            "sources": sources,
            "offered": form.OFFERED,
            "sources_offered": form.SOURCES_OFFERED,
            "source_names": [b.name for b in sources if b.name],
            "plant_names": [b.name for b in plants if b.name],
            "sizing": sizing_request or form.Sizing(),
            "sizing_rows": sizing_rows,
            "period": period,
            "max_days": form.MAX_DAYS,
            "result": result,
            "error": error,
            "css_version": CSS_VERSION,
        },
    )


@app.get("/", response_class=HTMLResponse)
def first_page(request: Request):  # type: ignore[no-untyped-def]
    return page(request, *form.first_boxes(), form.Period())


def _index(action: str, prefix: str, n: int) -> int | None:
    rest = action.removeprefix(prefix)
    return int(rest) if rest.isdigit() and int(rest) < n else None


@app.post("/", response_class=HTMLResponse)
async def submit(request: Request):  # type: ignore[no-untyped-def]
    data = await request.form()
    posted = {k: v for k, v in data.items() if isinstance(v, str)}
    plants = form.read_boxes(posted, "plant")
    sources = form.read_boxes(posted, "source")
    period = form.Period.read(posted)  # kept across every button (WX-041)
    wish = form.Sizing.read(posted)  # kept across every button too
    taken = {b.values["name"] for b in [*plants, *sources]}
    action = posted.get("action", "")
    if action == "add":
        plants.append(form.new_box(form.OFFERED[0], taken))
    elif action == "add_source":  # SRC-043
        sources.append(form.new_box(form.SOURCES_OFFERED[0], taken, "source"))
    elif action.startswith("remove:") and len(plants) > 1:  # UI-019: never the last box
        i = _index(action, "remove:", len(plants))
        if i is not None:
            del plants[i]
    elif action.startswith("remove_source:") and len(sources) > 1:
        i = _index(action, "remove_source:", len(sources))
        if i is not None:
            del sources[i]
    elif action.startswith("import:"):  # spec 0014: loads the file, runs nothing (IMP-001)
        i = _index(action, "import:", len(plants))
        if i is not None:
            upload = data.get(f"p{i}.upload")
            content = None  # browsers post an empty file name when no file was chosen
            if isinstance(upload, UploadFile) and upload.filename:
                content = await upload.read(form.MAX_IMPORT_BYTES + 1)  # enough to see "too big"
            form.import_into(plants[i], content)
    elif action == "run" and plants and not any(b.redrawn for b in [*plants, *sources]):
        result, error = simulate(plants, sources, period)
        return page(request, plants, sources, period, result, error, wish)
    elif action == "size" and plants and not any(b.redrawn for b in [*plants, *sources]):
        rows = size(plants, sources, wish)
        return page(request, plants, sources, period, sizing_request=wish, sizing_rows=rows)
    return page(request, plants, sources, period, sizing_request=wish)
