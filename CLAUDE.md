# kioze-sim-lib

Python library simulating power generating installations (PV, HAWT, VAWT, biogas, boiler + heat store)
from input parameters and weather. Spec-driven: read `specs/README.md` and `specs/constitution.md` first.

## Workflow rules
- No feature code without an `approved` spec in `specs/`. If asked for something unspecified, write or
  update the spec first and get it confirmed.
- Every requirement ID gets a test marked `@pytest.mark.spec("ID")`.
- Do not resolve a spec's open questions by guessing; ask the user.
- The user is not a data scientist or electrical engineer: explain domain terms plainly in specs.

## Commands
- `uv sync --all-extras` install
- `uv run pytest` tests
- `uv run python scripts/spec_check.py` spec/test traceability
- `uv run ruff check . && uv run mypy` lint and types
