---
id: 0017
title: One app package
prefix: APP
status: implemented
---

# 0017 One app package

## Problem
The repository has four packages: the library, the command-line tool, the web app and
`kiozesim-utils`, a package that exists only so the two apps can share code (spec 0016). Two apps
that share a package, a config format and a list of source types are really one app with two
faces. Keeping them apart costs a package, two dependency lists to keep in step, and duplicate code:
the tool's config reader and the web form each keep their own list of source types and their own
code that turns settings into a plant or source.

So the web app becomes a sub-command of the tool, `kiozesim-tool ui`, and the shared package
moves into the tool. The repository ends up with two packages: the library and the app.

## Scope
In:
- Moving `kiozesim_ui` into `kiozesim_tool.ui` and `kiozesim_utils` into `kiozesim_tool`.
- A `kiozesim-tool ui` sub-command replacing the `kiozesim-ui` command.
- One list of plant and source types, and one way to build a plant or source from settings, used
  by both the YAML config and the web form.
- Updating specs, the constitution, `CLAUDE.md`, `README.md`, `.claude/launch.json`.

Out:
- Any change to what the web page or `sink` does, beyond the command that starts the page.
- Merging the two identical weather day files (`examples/day_weather.csv`, the UI's sample day);
  they stay separate.
- Changes to the library.

## Domain notes
- *Sub-command*: a word after the program name choosing what it does, like `git commit` vs
  `git push`. `kiozesim-tool sink ...` streams readings; `kiozesim-tool ui` starts the web page.
- *Registry*: a lookup table from a type name (`pv`, `digester`) to the class that builds it. With
  one registry, adding a source type makes it appear in the config and the web page at once.

Target layout:

```
kiozesim-tool/
  pyproject.toml          install name "kiozesim-tool"; also fastapi, uvicorn, jinja2, matplotlib
  examples/
  src/kiozesim_tool/
    cli.py                `sink` and `ui` sub-commands
    config.py sink.py mqtt.py player.py
    boxes.py              the shared type registry and builders (new)
    wiring.py weather.py  from kiozesim_utils
    ui/                   from kiozesim_ui: app.py form.py chart.py templates/ static/ sample_weather.csv
  tests/                  today's tool tests plus the UI and utils tests
```

## Requirements
- **APP-001** The workspace MUST have exactly two packages, `kiozesim/` and `kiozesim-tool/`; the
  folders `kiozesim-ui/` and `kiozesim-utils/` MUST NOT remain, and no code MAY import
  `kiozesim_ui` or `kiozesim_utils`.
- **APP-002** The web app MUST live in `kiozesim_tool.ui`, with its templates, static files and
  sample weather inside that sub-package; wiring and the weather file source MUST live in
  `kiozesim_tool.wiring` and `kiozesim_tool.weather`.
- **APP-003** `kiozesim-tool ui` MUST start the web server, with `--host` and `--port` options
  defaulting to `127.0.0.1` and `8000`. There MUST be no `kiozesim-ui` command.
- **APP-004** Installing `kiozesim-tool` MUST install everything the web UI needs; no extra is
  needed.
- **APP-005** `kiozesim_tool.boxes` MUST hold the only list of plant types and of source types the
  apps offer, and MUST provide the functions that build a plant or a source from its settings
  (including loading a bundled datasheet given by name). Both offer the same plant types: those
  whose spec is implemented (UI-005), so the config no longer takes a draft type. The config reader and the web form MUST
  both use them and MUST NOT keep their own type lists or datasheet lookup.
- **APP-006** The move MUST NOT change behaviour: the tool, UI and utils tests that existed before
  MUST pass with only import and path edits, apart from the test of the start command (APP-003).

## Acceptance
- Every APP requirement has a test; `uv run pytest`, `uv run python scripts/spec_check.py`,
  `ruff` and `mypy` are green.
- Spec edits on approval: 0010 (UI-016 retired in favour of APP-003; paths in UI-001, UI-002,
  UI-011, UI-017 become `kiozesim_tool/ui/`), 0016 (SRC-010 retired in favour of APP-001; SRC-006,
  SRC-011, SRC-012 name `kiozesim_tool`), constitution 14 (two packages), `CLAUDE.md`, `README.md`.
  Spec 0009 stays as the record it is.

## Open questions
- [x] Web dependencies: always installed (APP-004; decided 2026-10-12).
- [x] Old `kiozesim-ui` command: removed (APP-003; decided 2026-10-12).
- [x] What "combine" covers: one type registry and builder (APP-005); the weather day files stay
      two copies (decided 2026-10-12).

## Changelog
- 2026-10-12 created (draft)
- 2026-10-12 approved
- 2026-10-12 APP-005: config and page offer the same plant types (found while building: the config
  also took the draft `boiler`)
- 2026-10-12 implemented
