"""Traceability check between specs/ and every package's tests/.

Fails when: a requirement ID is malformed or duplicated; a spec marked `implemented` has a
requirement without a test; a `@pytest.mark.spec("ID")` references an unknown requirement.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ_RE = re.compile(r"^- \*\*([A-Z]+-\d{3})\*\*", re.M)
MARK_RE = re.compile(r"""mark\.spec\(\s*["']([A-Z]+-\d{3})["']""")
FRONT_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
STATUSES = {"draft", "approved", "implemented"}


def front_matter(text: str) -> dict[str, str]:
    m = FRONT_RE.match(text)
    if not m:
        return {}
    pairs = (line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    return {k.strip(): v.split("#")[0].strip() for k, v in pairs}


def main() -> int:
    errors: list[str] = []
    reqs: dict[str, tuple[str, str]] = {}  # id -> (spec path, status)

    for spec in sorted((ROOT / "specs").glob("[0-9]*/spec.md")):
        rel = spec.relative_to(ROOT).as_posix()
        text = spec.read_text()
        fm = front_matter(text)
        status, prefix = fm.get("status", ""), fm.get("prefix", "")
        if status not in STATUSES:
            errors.append(f"{rel}: status must be one of {sorted(STATUSES)}")
        for rid in REQ_RE.findall(text):
            if not rid.startswith(prefix + "-"):
                errors.append(f"{rel}: {rid} does not match prefix '{prefix}'")
            if rid in reqs:
                errors.append(f"{rel}: duplicate requirement {rid} (also in {reqs[rid][0]})")
            reqs[rid] = (rel, status)
        if (
            status == "approved"
            and "- [ ]" in text.split("## Open questions")[-1].split("## Changelog")[0]
        ):
            errors.append(f"{rel}: approved spec still has open questions")

    covered: dict[str, list[str]] = {}
    for test in sorted(ROOT.glob("*/tests/**/test_*.py")):  # one tests/ per package (0009)
        name = test.relative_to(ROOT).as_posix()
        for rid in MARK_RE.findall(test.read_text()):
            covered.setdefault(rid, []).append(name)
            if rid not in reqs:
                errors.append(f"{name}: marker references unknown requirement {rid}")

    for rid, (rel, status) in sorted(reqs.items()):
        if status == "implemented" and rid not in covered:
            errors.append(f"{rel}: {rid} is implemented but has no test")

    for e in errors:
        print("FAIL", e)
    print(f"{len(reqs)} requirements, {len(covered)} covered, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
