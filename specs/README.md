# Spec-driven development

**The spec is the source of truth. Code and tests follow it, never the other way round.**

## Lifecycle of a feature

1. **Specify.** Copy `_template.md` to `specs/NNNN-short-name/spec.md`. Write the problem, scope, and
   numbered requirements (`PV-001`, ...). Each requirement is one testable sentence using MUST/SHOULD.
   Status: `draft`.
2. **Clarify.** Resolve every item under *Open questions*. A spec with open questions cannot be approved.
3. **Approve.** Set `status: approved`. From here, requirement text only changes through a spec edit
   (and a changelog line), never silently in code.
4. **Plan.** Write `plan.md` next to the spec: design, modules touched, external libs, risks.
5. **Test first.** Add golden cases under `kiozesim/tests/golden/<plant>/` (see its README). For each requirement write at least one test marked `@pytest.mark.spec("PV-001")`.
   Tests fail first.
6. **Implement** until the tests pass.
7. **Verify.** `uv run python scripts/spec_check.py` plus `pytest`, `ruff`, `mypy`. Set
   `status: implemented`.

## Statuses

| Status | Meaning | `spec_check` enforces |
|---|---|---|
| `draft` | Being written, open questions allowed | IDs well-formed and unique |
| `approved` | Agreed, not yet built | same as draft |
| `implemented` | Built | every requirement has >= 1 test marked with its ID |

Additionally, every `@pytest.mark.spec("ID")` in any package's `tests/` must reference an existing
requirement.

## Requirement format

Inside `spec.md`, a requirement is a list item starting with its ID in bold:

```
- **PV-001** The plant MUST return 0 kW when `ghi` is 0.
```

IDs are `<PREFIX>-<3 digits>`, unique across all specs. The prefix is set in the spec's front matter.

## Layout

```
specs/
  constitution.md          project-wide rules every spec obeys
  _template.md             spec template
  0001-core-plant-interface/
    spec.md                what and why (requirements)
    plan.md                how (optional until approved)
```

Paths in specs: `kiozesim/datasheets/` (no `src/`) means inside the library's Python package,
`kiozesim/src/kiozesim/datasheets/`. Paths with `src/` or `tests/` are folders in the repository
(constitution 14).
