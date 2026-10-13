# kioze-sim-lib

Python library simulating power generating installations (PV, HAWT, VAWT, gas engine/CHP fed by a biogas digester, boiler + heat store)
from input parameters and weather. Spec-driven: read `specs/README.md` and `specs/constitution.md` first.

uv workspace with two packages: library `kiozesim/` (import `kiozesim`) and the app
`kiozesim-tool/` (`kiozesim_tool`: the `sink` command, the web UI in `kiozesim_tool.ui`, and the
code both share: plant/source types, weather sources, wiring; spec 0017). Code in
`<package>/src/`, tests in `<package>/tests/`. Only the library's `tests/` has an `__init__.py`; the
app's test folder must not (it would clash with the library's `tests` package under pytest).

## Workflow rules
- No feature code without an `approved` spec in `specs/`. If asked for something unspecified, write or
  update the spec first and get it confirmed.
- Every requirement ID gets a test marked `@pytest.mark.spec("ID")`.
- Do not resolve a spec's open questions by guessing; ask the user.
- The user is not a data scientist or electrical engineer: explain domain terms plainly in specs.

## Commands
- `uv sync --all-packages --all-extras` install
- `uv run pytest` tests
- `uv run python scripts/spec_check.py` spec/test traceability
- `uv run ruff check . && uv run mypy` lint and types
- `uv run kiozesim-tool ui` web UI at http://127.0.0.1:8000 (specs 0010, 0017)
- `uv run kiozesim-tool sink 15min --config kiozesim-tool/examples/sink.yaml` stream readings (spec 0011)
- `uv run kiozesim-tool sink 15min --config kiozesim-tool/examples/mqtt.yaml` stream to a local MQTT broker (spec 0012)
- `uv run kiozesim-tool sink 1h --config kiozesim-tool/examples/real_weather.yaml` real weather from Open-Meteo (spec 0018)
