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
