"""The web server: one server-rendered page, every button a plain form post (spec 0010)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from kiozesim import Portfolio, TimeSeries
from kiozesim_ui import form
from kiozesim_ui.chart import power_svg

HERE = Path(__file__).resolve().parent

app = FastAPI(title="kiozesim")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


@dataclass(frozen=True)
class Result:
    energy_kwh: dict[str, float]  # per plant plus "total"
    chart: Markup


def sample_weather() -> pd.DataFrame:
    """The bundled sample weather (UI-011): hourly, UTC, period-start labels."""
    return pd.read_csv(HERE / "sample_weather.csv", index_col="time", parse_dates=True)


def simulate(boxes: list[form.Box]) -> tuple[Result | None, str]:
    """Run all boxes as one portfolio. Returns (result, page-level error)."""
    plants = form.build_plants(boxes)
    if plants is None:
        return None, ""
    weather = sample_weather()
    inputs: dict[str, TimeSeries] = {}
    for p in plants:
        if p.inputs_model is not None:
            inputs[p.name] = p.inputs_model.from_frame(weather)
    try:
        power = Portfolio(plants).simulate(inputs)
    except (ValueError, TypeError, ImportError) as e:
        return None, str(e)
    step_h = (power.index[1] - power.index[0]) / pd.Timedelta(hours=1)
    energy = {str(c): float(power[c].sum() * step_h) for c in power.columns}
    return Result(energy, Markup(power_svg(power))), ""


def page(request: Request, boxes: list[form.Box], result: Result | None = None, error: str = ""):  # type: ignore[no-untyped-def]  # noqa: E501
    return templates.TemplateResponse(
        request,
        "page.html",
        {"boxes": boxes, "offered": form.OFFERED, "result": result, "error": error},
    )


@app.get("/", response_class=HTMLResponse)
def first_page(request: Request):  # type: ignore[no-untyped-def]
    return page(request, [form.new_box(form.OFFERED[0], set())])


@app.post("/", response_class=HTMLResponse)
async def submit(request: Request):  # type: ignore[no-untyped-def]
    posted = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    boxes = form.read_boxes(posted)
    action = posted.get("action", "")
    if action == "add":
        taken = {b.values["name"] for b in boxes}
        boxes.append(form.new_box(form.OFFERED[0], taken))
    elif action.startswith("remove:") and len(boxes) > 1:  # UI-019: never the last box
        index = action.removeprefix("remove:")
        if index.isdigit() and int(index) < len(boxes):
            del boxes[int(index)]
    elif action == "run" and boxes and not any(b.redrawn for b in boxes):
        result, error = simulate(boxes)
        return page(request, boxes, result, error)
    return page(request, boxes)
