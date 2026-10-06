# 0009 Monorepo layout: plan

How to build [spec.md](spec.md).

## Design in one paragraph
Everything that is the library today (`src/kioze_sim/`, `tests/`, `examples/`) moves with `git mv` into
`kiozesim/`, and the import is renamed `kioze_sim` → `kiozesim` with a search-and-replace. The root
`pyproject.toml` is split: the `[project]`, extras and hatch settings go to `kiozesim/pyproject.toml`.
The root keeps only `[tool.uv.workspace]`, the `dev` dependency group, and shared ruff/mypy/pytest
settings, with paths updated to the new folders. `kiozesim-tool/` and `kiozesim-ui/` get a minimal
`pyproject.toml` (hatchling, `dependencies = ["kiozesim"]`, `[tool.uv.sources] kiozesim = { workspace
= true }`) and an empty `src/<name>/__init__.py`. The work lands as one commit: the move cannot be
green on its own, because the DS-005 wheel test builds from `kiozesim/`, which needs the new
`kiozesim/pyproject.toml`.

## Modules touched

| File | Change |
|---|---|
| `pyproject.toml` | virtual root: workspace members, `dev` group, shared tool config; `testpaths` lists each package's `tests/`; mypy `files` lists each `src/` |
| `kiozesim/pyproject.toml` | **new**: today's `[project]` (name `kiozesim`), extras, hatch `packages = ["src/kiozesim"]` |
| `kiozesim-tool/pyproject.toml`, `kiozesim-ui/pyproject.toml` | **new**: skeleton packages depending on `kiozesim` via workspace |
| `kiozesim-tool/src/kiozesim_tool/__init__.py`, `kiozesim-ui/src/kiozesim_ui/__init__.py` | **new**: empty (REPO-007) |
| `src/kioze_sim/**` → `kiozesim/src/kiozesim/**` | moved; `kioze_sim` → `kiozesim` in imports, `importlib.resources.files(...)` and docstrings |
| `tests/**` → `kiozesim/tests/**` | moved; imports renamed; `from tests.harness` changed (see Risks) |
| `examples/**` → `kiozesim/examples/**` | moved; run line in docstring becomes `uv run python kiozesim/examples/pv.py` |
| `scripts/spec_check.py` | scan `*/tests/**/test_*.py` instead of `tests/` (REPO-009) |
| `kiozesim/tests/test_layout.py` | **new**: REPO-001..013 checks |
| `specs/constitution.md`, specs 0001–0008 (spec and plan) | paths and names; a changelog line in each spec whose requirement text changes (0008: EX-001/002/003/005) |
| `CLAUDE.md`, `README.md` | new layout, `uv sync --all-packages --all-extras` |
| `uv.lock` | regenerated |

## Risks
- **Two packages named `tests`.** Chosen fix, verified while building: pytest runs with
  `--import-mode=importlib`; the library's `tests/` keeps its `__init__.py` and imports the harness
  relatively (`from .harness import ...`); the apps' `tests/` folders have no `__init__.py`, so pytest
  names their modules after the dashed folder (`kiozesim-tool/...`) and they cannot clash. Rejected:
  dropping the library's `__init__.py`, because pytest then names its modules `kiozesim.tests.*`, which
  shadows the real `kiozesim` package and breaks every import.
- **The wheel test in 0007 (DS-005)** builds from `PKG.parent.parent`, which becomes `kiozesim/`. That
  is the right folder for the new `pyproject.toml`; re-checked, it builds and passes.
- **Golden case script** `kiozesim/tests/golden/pv/make_pvgis_case.py` must still not import the
  library (it only uses paths relative to itself, so the move should not affect it).
- **Old commit history.** `git mv` keeps file history, but `git log` on the new paths needs
  `--follow`.
