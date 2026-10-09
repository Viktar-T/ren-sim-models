# 0010 Plan

## Libraries (kiozesim-ui only)
- `fastapi` (server), `uvicorn` (runs it), `jinja2` (templates), `python-multipart` (reads HTML form
  posts), `matplotlib` (chart), `kiozesim[pv]` (PV needs pvlib to run).
- Dev: `httpx`, needed by FastAPI's `TestClient`.

## Modules in `kiozesim-ui/src/kiozesim_ui/`
- `form.py`: no web code. `OFFERED` plant types, field descriptions read from each params model's
  `model_fields` (kind, range, choices, default), turning posted form strings into params models and
  collecting errors per (box, field).
- `chart.py`: `power_svg(frame) -> str`, matplotlib `Figure` (no pyplot, so no global state).
- `app.py`: the FastAPI `app`. `GET /` = one box. `POST /` with `action` = `add` | `apply` | `run`.
- `__main__.py`: `main()`, argparse `--host`/`--port`, `uvicorn.run`. Script `kiozesim-ui`.
- `templates/page.html`, `static/style.css`, `sample_weather.csv` (copy of the example's).

## Form encoding
Box `i` posts `p{i}.type`, `p{i}.shown_type` (hidden: the type its fields were drawn for) and
`p{i}.<field>`. A hidden `n` holds the box count. A box whose `type` differs from `shown_type` is
redrawn with the new type's defaults, and Run then does not simulate (UI-005).

Empty strings are left out so pydantic reports "Field required". The datasheet name is turned into
the model with `<Datasheet>.bundled(name)`. Other values are passed as strings, and pydantic's lax
mode converts them.

## Energy
kWh = sum of kW x step in hours (the weather's step).

## Tests (`kiozesim-ui/tests/test_ui.py`)
`TestClient` plus HTML checks with plain string and regex searches. The UI-005 check reads spec front
matter: prefix to registry key (`PV`→`pv`, `WIND`→`hawt`, `VAWT`→`vawt`, `BIO`→`biogas`,
`BOIL`→`boiler`).

## Touched elsewhere
- Root dev group gains `httpx`.

## HAWT support (2026-10-08, UI-007, UI-011, UI-018)
- `form.OFFERED` gains `hawt`. Its box needs no new template: fields come from `HAWTParams`.
- Yes/no fields (`bool` in the params model) get `Field.kind = "checkbox"`, value `"true"`/`"false"`.
  The template draws `<input type="checkbox" value="true">`, ticked when the value is `"true"`.
  `read_boxes` reads a missing checkbox in a posted (not redrawn) box as `"false"`, because
  browsers send nothing for an unticked box.
- Errors with no field (`loc == ()`, from a params model validator such as HAWT's height check) are
  stored under the key `""` and drawn at the top of the box (`<p class="error" data-for="p{i}">`).
- `sample_weather.csv` is now its own file: same sun and temperature as before, wind replaced by a
  made-up breezy day (about 4–9.5 m/s at 10 m, stronger in the afternoon) and a `pressure_hpa`
  column (a slow fall from 1012 to 1006 hPa, as before an approaching front). The UI-011 test
  checks the columns and the wind range instead of equality with `pv_weather.csv`.
- `pyproject.toml`: `kiozesim[pv,wind]`.

## VAWT support (2026-10-09, UI-005, UI-010)
- `form.OFFERED` gains `vawt`; fields come from `VAWTParams`, no template change.
- The datasheet drop-down lists the `vawt` shelf: two real products and two `example_` datasheets.
- Test: PV + HAWT + VAWT run for each bundled VAWT datasheet gives non-zero VAWT energy.
