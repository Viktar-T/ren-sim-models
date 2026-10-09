# 0014 Plan

## Libraries
- `pyyaml` becomes a direct dependency of `kiozesim-ui` (it was only reached through `kiozesim`).
  `python-multipart`, already there, reads the uploaded file.

## Form encoding (adds to spec 0010's plan)
- The `<form>` gets `enctype="multipart/form-data"`. Posts without a file still parse the same way,
  so the existing tests keep posting plain form data.
- Box `i` gains `p{i}.upload` (the file picker) and, once it holds an import, the hidden
  `p{i}.imported`. **Import** posts `action=import:{i}`.
- The hidden field holds the YAML text **base64-encoded** (letters, digits, `+/=` only). Browsers may
  rewrite line breaks inside form values; base64 has none, so the text comes back byte for byte.
- The imported entry's drop-down value is `form.UPLOADED = ":uploaded"`. No bundled file name
  (DS-009: letters, digits, `_`) or windpowerlib type code starts with `:`, so it cannot clash.

## `form.py` (still no web code)
- `Field.datasheet: bool` marks the datasheet drop-down; `sheet_model(type)` finds the type's
  `Datasheet` subclass from its params model.
- `Box` gains `imported` (YAML text), `sheet` (the checked `Datasheet`), `carried` (base64 for the
  hidden field) and `options(field)`, which lists `(value, label)` pairs with the import first
  (IMP-003).
- `read_sheet(type, text)`: `yaml.safe_load` (IMP-009), mapping check, `model_validate`. Raises
  `ValueError` with pydantic's messages as `field: message`, joined by `; `; an error without a
  field keeps just its message (IMP-008).
- `import_into(box, content)`: size cap `MAX_IMPORT_BYTES = 100 * 1024`, UTF-8 decode (a leading
  byte-order mark is allowed), `read_sheet`. On success it sets the box's import and selects
  `UPLOADED`; on failure it writes the reason under the error key `upload`, leaving any earlier
  import in place.
- `read_boxes` decodes and re-checks `p{i}.imported` for boxes whose type did not change
  (IMP-005); a box whose type changed is rebuilt without it (IMP-006). A carried import that fails
  the check is dropped with an error next to the file picker.
- `build_plants` passes `box.sheet` for `UPLOADED`; `UPLOADED` with no import is an error next to
  the datasheet field.

## `app.py`
`POST /` keeps the parsed form. For `import:{i}` it reads `p{i}.upload` (at most
`MAX_IMPORT_BYTES + 1` bytes, so an oversized file is detected without reading it all) and calls
`form.import_into`. A file part with an empty file name (browsers send one when no file is chosen)
counts as no file.

## Template
- File picker row (`<input type="file" accept=".yaml,.yml">` plus **Import**) right under the
  datasheet row, label `import`, error cell `data-for="p{i}.upload"`.
- The file picker is 16em wide like the other inputs (`static/style.css`).
- Select options come from `box.options(f)`. Jinja's autoescaping covers the label, the hidden
  field and errors (IMP-009).

## Tests
Added to `kiozesim-ui/tests/test_ui.py` (it holds the page helpers; `post` gains a `files=`
argument). The UI-001 test now expects the `enctype`, and UI-006 ignores the `import` row's label.
