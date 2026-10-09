---
id: 0014
title: UI datasheet import
prefix: IMP
status: implemented
---

# 0014 UI datasheet import

## Problem
The web UI (spec 0010) only offers the datasheets bundled with the library. To try a product that
is not on the shelf, say a new solar module or a turbine with a power curve you were sent, you must
add a file to the library and restart the server. A quick import lets you pick your own datasheet
file in the plant box and run it right away.

## Scope
In:
- A file picker and an **Import** button in every plant box, for every offered plant type.
- Files in the same YAML layout as the bundled datasheets (spec 0007).
- The imported datasheet stays with its box while the page is open.

Out:
- Typing datasheet values into fields, or pasting YAML text.
- Saving imports: nothing is written to disk, and a reload forgets them.
- Reading manufacturer PDFs or other formats (CSV, JSON).
- Sharing one import between boxes (each box imports its own).
- Any change to the library: the UI uses the existing `Datasheet` models.

## Domain notes
- *Datasheet file*: a small text file in YAML, a simple `name: value` format. It holds the
  manufacturer, the model, an optional `source` and the product's values. A PV module, for example:

  ```yaml
  manufacturer: Acme
  model: X-400
  pdc0_w: 400               # rated power at standard test conditions
  gamma_pdc_per_k: -0.0035  # power lost per degree of extra cell heat, -0.35 %/degC
  ```

  The fields each plant type needs are those of its `Datasheet` model (`PVDatasheet`,
  `HAWTDatasheet`, `VAWTDatasheet`), the same check the bundled files pass. The bundled files under
  `kiozesim/datasheets/<type>/` are working examples to copy.
- *File upload without JavaScript*: a plain HTML form can send a file when it is marked
  `multipart/form-data` (the browser's standard way of attaching a file to a form). The page stays
  server-rendered (UI-001).
- *Hidden field*: an input the browser keeps in the form without showing it. After an import the
  server puts the file's text in one, so every later button press sends it back. This is how the
  page "remembers" the import with nothing stored on the server.
- *Safe YAML reader*: YAML readers can be told to build arbitrary Python objects, which a hostile
  file could abuse. The safe reader only builds plain values (text, numbers, lists, mappings).

## Requirements
- **IMP-001** Each plant box MUST have a file picker and an **Import** button. The page's form MUST
  be sent as `multipart/form-data` so it can carry the file, and pressing **Import** MUST return the
  page without running a simulation, like **Apply**.
- **IMP-002** The file MUST be read as YAML and checked with the `Datasheet` model of the box's
  selected plant type, the same model bundled files of that type pass. A `source` MUST NOT be
  required (DS-008 applies to bundled files only).
- **IMP-003** After a successful import, the box's datasheet drop-down MUST list one extra entry,
  first and selected, labelled `uploaded: <manufacturer> <model>`. No other box MUST change.
- **IMP-004** A box MUST hold at most one imported datasheet; a new import into the same box MUST
  replace the old one.
- **IMP-005** The imported datasheet MUST stay with its box across every later button press (**+**,
  **Apply** without a type change, **Remove** of another box, **Import** in another box, **Run**)
  until the page is reloaded or closed. The page MUST carry it in a hidden field; the server MUST NOT
  write it anywhere. On every submit the carried text MUST be checked again with the type's
  `Datasheet` model.
- **IMP-006** Changing a box's plant type MUST drop its imported datasheet.
- **IMP-007** **Run** with the imported entry selected MUST simulate that plant with the imported
  datasheet, giving the same energy as a bundled datasheet holding the same values.
- **IMP-008** If the file cannot be used, the page MUST come back with the error next to that box's
  file picker, all typed values and that box's earlier import kept, and no result. This covers: no
  file chosen, a file over 100 kB, a file that is not YAML or not a `name: value` mapping, and a
  datasheet the model rejects (the message MUST name the field, e.g.
  `pdc0_w: Input should be greater than 0`; an error with no single field, e.g. a power curve
  whose two lists differ in length, shows its message alone).
- **IMP-009** The file MUST be read with a safe YAML reader only, and any text from it (the drop-down
  label, the hidden field, error messages) MUST be HTML-escaped, so a file cannot add HTML or
  scripts to the page.

## Acceptance
Tests use FastAPI's `TestClient`, posting files as `multipart/form-data`, and check the returned
HTML. A PV import shows `uploaded: <manufacturer> <model>` first and selected; Run with it gives the
same PV energy as the bundled `jinko_solar_jkm440n_54hl4r_b` when the file holds the same values.
The import survives **+**, **Remove** of another box and **Run**, and is gone after a type change.
A HAWT import and a VAWT `power_curve` import (copies of bundled files with a new model name) run
with non-zero energy. Each failure in IMP-008 shows its error next to the file picker with the
typed values kept. A file whose `manufacturer` is `<script>alert(1)</script>` appears escaped. A
fresh page load after an import shows no `uploaded:` entry (the server kept nothing). No browser
tests.

## Open questions
- [x] How to get the datasheet in: upload a YAML file in the bundled layout (user, 2026-10-09).
- [x] How long it stays: only while the page is open, nothing saved (user, 2026-10-09).
- [x] One import per box, not shared between boxes (IMP-004, Scope).
- [x] 100 kB size limit (IMP-008). Real datasheet files are 1–3 kB; the limit keeps the
  hidden field well under the web server's 1 MB per-field cap.
- [x] Drop-down label `uploaded: <manufacturer> <model>`, listed first (IMP-003).

## Changelog
- 2026-10-09 created
- 2026-10-09 proposals confirmed by the user; approved
- 2026-10-09 implemented
