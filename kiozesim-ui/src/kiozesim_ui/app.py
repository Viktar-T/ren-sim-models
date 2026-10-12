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

from kiozesim_ui import form
from kiozesim_ui.chart import power_svg
from kiozesim_utils import wiring

HERE = Path(__file__).resolve().parent

app = FastAPI(title="kiozesim")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
# Changes with the stylesheet's content, so browsers fetch a changed file instead of a cached one.
CSS_VERSION = hashlib.sha256((HERE / "static" / "style.css").read_bytes()).hexdigest()[:12]


@dataclass(frozen=True)
class Result:
    energy_kwh: dict[str, float]  # per plant plus "total"
    chart: Markup


# The sample weather is one dateless day; the page runs it on this date (UI-011).
RUN_DAY = pd.date_range("2026-06-21", periods=24, freq="h", tz="UTC")


def simulate(
    plant_boxes: list[form.Box], source_boxes: list[form.Box]
) -> tuple[Result | None, str]:
    """Run all plants as one portfolio, fed by their wired sources. Returns (result, page error)."""
    built = form.build(plant_boxes, source_boxes)
    if built is None:
        return None, ""
    plants, sources = built
    wires = {b.name: b.wired for b in [*plant_boxes, *source_boxes]}
    try:
        power = wiring.run(sources, plants, wires, RUN_DAY)
    except wiring.WiringError as e:  # shown on the box it belongs to (SRC-022)
        for b in [*plant_boxes, *source_boxes]:
            if b.name == e.box:
                b.errors[""] = str(e)
                return None, ""
        return None, str(e)
    except (ValueError, TypeError, ImportError) as e:
        return None, str(e)
    step_h = (power.index[1] - power.index[0]) / pd.Timedelta(hours=1)
    energy = {str(c): float(power[c].sum() * step_h) for c in power.columns}
    return Result(energy, Markup(power_svg(power))), ""


def page(  # type: ignore[no-untyped-def]
    request: Request,
    plants: list[form.Box],
    sources: list[form.Box],
    result: Result | None = None,
    error: str = "",
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
            "result": result,
            "error": error,
            "css_version": CSS_VERSION,
        },
    )


@app.get("/", response_class=HTMLResponse)
def first_page(request: Request):  # type: ignore[no-untyped-def]
    return page(request, *form.first_boxes())


def _index(action: str, prefix: str, n: int) -> int | None:
    rest = action.removeprefix(prefix)
    return int(rest) if rest.isdigit() and int(rest) < n else None


@app.post("/", response_class=HTMLResponse)
async def submit(request: Request):  # type: ignore[no-untyped-def]
    data = await request.form()
    posted = {k: v for k, v in data.items() if isinstance(v, str)}
    plants = form.read_boxes(posted, "plant")
    sources = form.read_boxes(posted, "source")
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
        result, error = simulate(plants, sources)
        return page(request, plants, sources, result, error)
    return page(request, plants, sources)
