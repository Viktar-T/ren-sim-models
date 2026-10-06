---
id: 0009
title: Monorepo layout
prefix: REPO
status: done
---

# 0009 Monorepo layout

## Problem
The repository holds one thing today: the simulation library. We want to add a command-line tool and a
web app that use it. Putting all three in this repository means a change to the library and the
matching changes to the apps can land together in one commit.

The apps will need packages the library does not (a web framework, for example). Someone who only
wants the library should not have to install them. So each of the three becomes its own package with
its own dependency list, and the three sit next to each other in the repository root.

At the same time the library is renamed from `kioze_sim` to `kiozesim`, so the three names read as a
family: `kiozesim`, `kiozesim-tool`, `kiozesim-ui`.

## Scope
In:
- Moving the library into its own folder and renaming its import from `kioze_sim` to `kiozesim`.
- Turning the repository root into a uv workspace that lists the three packages.
- Empty skeletons for the tool and the UI: an importable package and a `pyproject.toml`, nothing more.
- Moving today's `tests/` and `examples/` into the library's folder.
- Updating paths and names in specs, the constitution, `CLAUDE.md`, `README.md`, tests, scripts and
  examples.

Out:
- Any tool or UI feature (commands, pages, choice of web framework). Each gets its own spec.
- Publishing to PyPI.
- Any change to how the library simulates. After the move, every existing test must pass with only
  import and path edits.

## Domain notes
- *Monorepo*: one repository holding several related packages. Large Python projects such as
  LangChain, Airflow and Pydantic AI work this way.
- *uv workspace*: uv's way of managing several packages in one repository. The root `pyproject.toml`
  lists the member folders. All members share one `uv.lock` and one virtual environment, and a member
  can depend on another member directly from the folder, without publishing it first.
- *Virtual root*: a workspace root that only lists members and shared dev tools and is not a package
  itself. Nobody can install "the root".
- *Install name vs import name*: the install name is what you `pip install` (`kiozesim-tool`, dashes
  allowed). The import name is what you write in code (`import kiozesim_tool`, dashes not allowed in
  Python, so they become underscores).
- *src layout*: a package's code sits in `<package>/src/<import_name>/` instead of directly in
  `<package>/<import_name>/`. This stops tests from accidentally importing the loose source folder
  instead of the installed package, so tests check what a user actually gets.

Target layout:

```
kioze-sim-lib/
  pyproject.toml          workspace members + shared dev tools (virtual root)
  uv.lock
  specs/                  all specs, for all packages
  scripts/                spec_check.py and other repo tooling
  kiozesim/
    pyproject.toml        install name "kiozesim", the library
    src/kiozesim/         today's src/kioze_sim/, including datasheets/
    tests/                today's tests/, including golden/
    examples/             today's examples/
  kiozesim-tool/
    pyproject.toml        install name "kiozesim-tool"
    src/kiozesim_tool/
  kiozesim-ui/
    pyproject.toml        install name "kiozesim-ui"
    src/kiozesim_ui/
```

## Requirements
- **REPO-001** The repository root MUST contain exactly three package folders, `kiozesim/`,
  `kiozesim-tool/` and `kiozesim-ui/`, each with its own `pyproject.toml`.
- **REPO-002** The root `pyproject.toml` MUST declare a uv workspace whose members are exactly those
  three folders, and MUST NOT declare a `[project]` table (the root is not installable).
- **REPO-003** The install and import names MUST be: `kiozesim` → `kiozesim`, `kiozesim-tool` →
  `kiozesim_tool`, `kiozesim-ui` → `kiozesim_ui`. Each package's code MUST live in
  `<folder>/src/<import name>/`.
- **REPO-004** The library code MUST move from `src/kioze_sim/` to `kiozesim/src/kiozesim/` with no
  change in behaviour: all tests that existed before the move MUST pass with only import and path edits.
- **REPO-005** The library MUST keep today's dependencies and optional extras (`pv`, `wind`, `system`,
  `fmu`) and MUST NOT depend on `kiozesim-tool` or `kiozesim-ui`.
- **REPO-006** `kiozesim-tool` and `kiozesim-ui` MUST depend on `kiozesim` through the workspace (from
  the folder, not from PyPI).
- **REPO-007** Until their own specs are approved, `kiozesim_tool` and `kiozesim_ui` MUST contain only
  an `__init__.py`, and each MUST be importable.
- **REPO-008** After `uv sync --all-packages --all-extras`, running `uv run pytest`,
  `uv run python scripts/spec_check.py`, `uv run ruff check .` and `uv run mypy` from the root MUST
  cover all three packages.
- **REPO-009** `specs/` and `scripts/` MUST stay at the repository root, and `spec_check.py` MUST find
  `@pytest.mark.spec` tests in every package.
- **REPO-010** Each package's tests MUST live in `<folder>/tests/`; the library's existing tests,
  including `golden/`, MUST move to `kiozesim/tests/`. No `tests/` folder MUST remain at the root.
  Only the library's `tests/` MAY be a Python package (have an `__init__.py`); the apps' `tests/`
  MUST NOT, because pytest would then see two packages named `tests` and mix up same-named files.
- **REPO-011** The examples MUST move from `examples/` to `kiozesim/examples/` and still meet spec 0008,
  with its paths read relative to `kiozesim/` (0008 is amended to say so). No `examples/` folder MUST
  remain at the root.
- **REPO-012** Outside `.git/`, this spec's folder (which describes the rename) and spec changelog
  lines, no file MUST still contain `kioze_sim`, and the only remaining `kioze-sim` MUST be the
  repository folder name.
- **REPO-013** The constitution, specs 0001–0008, `CLAUDE.md` and `README.md` MUST describe the new
  paths and the install command `uv sync --all-packages --all-extras`.

## Acceptance
Checked once, when the move was made: the full suite, `spec_check`, `ruff` and `mypy` passed
from the root. The layout tests were removed afterwards; this spec is a record (status `done`).

## Open questions
- [x] Tests: per package, `kiozesim/tests/` (REPO-010).
- [x] Examples: inside the library, `kiozesim/examples/` (REPO-011).
- [x] Tool and UI skeletons: created now (REPO-007).
- [x] Library folder name: `kiozesim/`, no `-core`.

## Changelog
- 2026-10-06 created
- 2026-10-06 open questions resolved (per-package tests, examples in `kiozesim/`, skeletons now,
  folder `kiozesim/`), approved
- 2026-10-06 REPO-010: only the library's `tests/` may have an `__init__.py` (found while building)
- 2026-10-06 REPO-012: this spec's own folder is exempt, since it has to name the old package
- 2026-10-06 implemented
- 2026-10-06 status `done`: one-off move, kept as a record; its layout tests removed
