---
id: 0010
title: Web UI
prefix: UI
status: implemented
---

# 0010 Web UI

## Problem
To simulate a plant today you write Python. The web UI lets someone set up one or more plants in a
form, press one button and see the result, without writing code.

It is an engineering tool: a plain page like a native Windows dialog. Labelled fields in grouped
boxes, a button, the result. No animations, no themes, no frameworks.

## Scope
In:
- One page, rendered on the server. A box of input fields per plant, a **+** button below the last
  box to add another plant, one **Run** button, the result under it.
- Plant types whose spec is `implemented` (PV, HAWT; VAWT once spec 0004 is implemented). The app
  installs the engines those types need (`kiozesim[pv,wind]`).
- Bundled datasheets (spec 0007), plus a datasheet imported from a YAML file (spec 0014).
- One fixed sample weather file used for every run: one made-up sunny, breezy June day, hourly,
  with the columns every offered plant type needs.
- A command that starts the server.

Out:
- Any weather input in the UI (upload, choice of file, fetching online).
- Typing in your own datasheet values.
- Saving or loading setups or results; downloads. (Importing a datasheet file is spec 0014.)
- Field descriptions/tooltips.
- Browser tests (behaviour in a real browser is checked by hand).
- User accounts, deployment, any change to how the library simulates.

## Domain notes
- *Server-side rendering*: the server builds the whole HTML page in Python and sends it to the
  browser. Pressing a button sends the form back to the server, which builds the next page. The
  browser only displays; there is no app logic in JavaScript. It is how web pages worked before
  JavaScript apps, and it suits a form-and-button tool.
- *FastAPI*: a small Python library for writing web servers, one Python function per URL.
- *Jinja2*: a template language. An HTML file with gaps (`{{ value }}`) and loops that Python fills
  in to make the final page.
- *Portfolio*: the library's way to run several plants on one time axis and add them up
  (spec 0001, CORE-005). One plant on the page is a portfolio of one.

## Requirements

### Page
- **UI-001** The server MUST render the page in Python from Jinja2 templates in
  `kiozesim_ui/templates/`. Each button press MUST be a normal HTML form submission answered with a
  freshly rendered page.
- **UI-002** The page MUST NOT load anything from outside the server (no CDN, web fonts or analytics).
  Any CSS or JavaScript MUST be served from `kiozesim_ui/static/`.
- **UI-003** The page MUST look like a plain native form: system font, grey/white, one bordered
  group box (`<fieldset>`) per plant, no animations, no images except the chart.

### Plants on the page
- **UI-004** The first page MUST show one plant box. A **+** button below the last box MUST return
  the page with one more box, keeping everything already typed in the other boxes.
- **UI-019** Each box MUST have a **Remove** button next to its **Apply** button that returns the
  page without that box, keeping everything typed in the other boxes. When only one box is left,
  it MUST have no **Remove** button.
- **UI-005** Each box MUST have a plant type selector listing the offered plant types, which MUST be
  exactly the types whose spec is `implemented`. Changing the type MUST redraw that box with the new
  type's fields when the form is next submitted (an **Apply** button next to the selector does
  that with no JavaScript). A box whose type was just changed MUST NOT be simulated in that submit.
- **UI-006** A box's fields MUST be built from that type's params model (`PlantParams` subclass), so
  a newly implemented plant type needs no new template. Each field MUST be labelled with its name as
  written in the model (e.g. `tilt_deg`; the unit is in the name, constitution 9) and pre-filled with
  its default when it has one.
- **UI-007** A number field MUST carry the allowed range from the model (`min`, `max`). A field with
  a fixed set of values (e.g. `mounting`) MUST be a drop-down of those values. A yes/no field (e.g.
  `density_correction`) MUST be a checkbox, ticked when its default is true; an unticked box MUST
  mean false (a browser does not send unticked boxes, so the server reads a missing value as false).
- **UI-008** The datasheet field MUST be a drop-down of the bundled datasheet names for that plant
  type (`Datasheet.available()`, spec 0007), plus the box's imported datasheet, if any (spec 0014).
- **UI-009** A new box's `name` field MUST be pre-filled with a name not yet used on the page
  (`pv-1`, `pv-2`, ...).

### Running
- **UI-010** There MUST be exactly one **Run** button. It MUST simulate every plant on the page in
  one go, through `Portfolio`, with the sample weather (UI-011).
- **UI-011** The weather MUST be `kiozesim_ui/sample_weather.csv`, shipped inside the UI package so
  the installed app does not depend on the repository's `examples/` folder: one made-up day, hourly,
  UTC, holding every column any offered plant type requires (today `ghi_w_m2`, `temp_air_c`,
  `wind_speed_m_s` at 10 m, `pressure_hpa`). The wind MUST be breezy enough (about 4–10 m/s at
  10 m) that a large wind turbine visibly produces power.
- **UI-012** The server MUST build each plant from its pydantic params model and contain no physics
  of its own.
- **UI-013** If any input is invalid (including duplicate plant names), the page MUST come back with
  every error message shown next to the field it belongs to, all typed values kept, and no result.
- **UI-018** An error that belongs to no single field (e.g. two fields that contradict each other,
  such as `wind_height_m` not above `roughness_length_m`) MUST be shown at the top of its plant's
  box, not next to an unrelated field.

### Result
- **UI-014** After a run the page MUST show the energy in kWh over the whole period for each plant
  and for the total.
- **UI-015** After a run the page MUST show a chart of power in kW over time, one line per plant
  plus one for the total, drawn on the server with matplotlib as an SVG picture inside the page.
  The page MUST need no JavaScript.

### Server
- **UI-016** `uv run kiozesim-ui` MUST start the server. `--host` and `--port` options MUST exist,
  defaulting to `127.0.0.1` and `8000`.
- **UI-017** `kiozesim_ui` MUST use only the public API of `kiozesim` (no module whose name starts
  with `_`).

## Acceptance
Tests use FastAPI's `TestClient` to request pages and submit forms, and check the returned HTML: one
box on first load; **+** adds a box and keeps values; the type list matches implemented specs; PV
fields, ranges, defaults and the datasheet drop-down are present; Run with two PV plants shows both
energies and a total equal to their sum; a bad value shows its error next to the field; a HAWT box
shows its fields with `density_correction` as a checkbox, and unticking it is kept on the next page, and a PV + HAWT run gives a
non-zero HAWT energy; a contradiction between two HAWT fields shows at the top of the box; a VAWT box
offers the `vawt` shelf (real products and `example_` datasheets) and a PV + HAWT + VAWT run gives a
non-zero VAWT energy for each bundled VAWT datasheet. A test checks
the templates and static files reference no outside URL. No browser tests.

## Open questions
- [x] Chart library: matplotlib, drawn on the server as SVG, no JavaScript (UI-015).

## Changelog
- 2026-10-06 created
- 2026-10-06 reworked: server-side rendered, sample weather only, bundled datasheets only, no
  saving, no tooltips, no browser tests
- 2026-10-06 chart: matplotlib SVG (UI-015); UI-005 Apply button for type change; approved
- 2026-10-06 implemented
- 2026-10-08 HAWT support: yes/no drop-down (UI-007), sample weather owns its columns and gets a
  breezy day plus `pressure_hpa` (UI-011, no longer a copy of `pv_weather.csv`), box-level errors
  (UI-018), app installs `kiozesim[pv,wind]`; back to draft
- 2026-10-08 yes/no fields are checkboxes, not drop-downs (UI-007); approved
- 2026-10-08 HAWT support implemented
- 2026-10-08 plant boxes can be removed (UI-019), except the last one
- 2026-10-09 VAWT support (spec 0004): no requirement change, VAWT acceptance added
- 2026-10-09 datasheet import (spec 0014): UI-008 lists the box's imported datasheet; Scope
  updated
