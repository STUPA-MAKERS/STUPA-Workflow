#!/usr/bin/env python3
"""Check the spec files in `specs/` and keep the index in `specs/README.md` current.

The script checks the rules for specs (`specs/style/specs/`): the file name, the
place in the tree, the front matter, the heading, the labels, `must` in the rule
text, the scope paths, `replaced_by`, unique numbers, the index, and every `§`
reference in the code. It needs only the Python standard library.

Usage:
    python3 scripts/check_specs.py          check, exit 1 on a violation
    python3 scripts/check_specs.py --write  write the index of specs/README.md, then check
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "specs"
README = SPECS / "README.md"

KINDS = {
    "style": ("S", "style"),
    "requirements/functional": ("F", "functional"),
    "requirements/non-functional": ("NF", "non-functional"),
}
KEYS = ["id", "title", "kind", "status", "owner", "updated", "replaced_by", "tests", "scope"]
REQUIRED = {"id", "title", "kind", "status", "owner", "updated", "scope"}
STATUSES = {"draft", "approved", "replaced", "removed"}
FILE_NAME = re.compile(r"^[0-9]{6}_[a-z0-9]+(-[a-z0-9]+)*\.md$")
FOLDER = re.compile(r"^[a-z0-9-]+$")
FULL_ID = re.compile(r"^(F|NF|S)(/[a-z0-9-]+)+/[0-9]{6}$")
TEST_ENTRY = re.compile(r"^[^:\s]+\.(py|ts):[A-Za-z_][A-Za-z0-9_.]*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LABEL = re.compile(r"^(Reason|Test):", re.MULTILINE)
MUST = re.compile(r"\bmust\b")
SECTION_REF = re.compile(r"§ ?((?:F|NF|S)/[a-z0-9/-]+/[0-9]{6})")
CODE_DIRS = ["backend/app", "backend/worker", "backend/tests", "frontend/src", "mcp", "typst"]
CODE_SUFFIXES = {".py", ".ts", ".html", ".scss"}
INDEX_START = "## Index\n"


@dataclass(frozen=True)
class Spec:
    """One parsed spec file."""

    path: Path
    full_id: str
    meta: dict[str, str | list[str]]
    keys: list[str]
    body: str


def _parse_front_matter(text: str) -> tuple[dict[str, str | list[str]], list[str], str] | None:
    """Return the keys, their order and the body, or None without front matter."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    meta: dict[str, str | list[str]] = {}
    keys: list[str] = []
    current: str | None = None
    for line in text[4:end].splitlines():
        if line.startswith("  - ") and current is not None:
            value = meta.setdefault(current, [])
            if isinstance(value, list):
                value.append(line[4:].strip().strip('"'))
            continue
        key, _, value = line.partition(":")
        current = key.strip()
        keys.append(current)
        meta[current] = value.strip() if value.strip() else []
    return meta, keys, text[end + 5 :]


def _kind_of(rel: Path) -> tuple[str, str, Path] | None:
    """Return the ID prefix, the kind and the path below the kind folder."""
    for folder, (prefix, kind) in KINDS.items():
        base = Path(folder)
        if rel.parts[: len(base.parts)] == base.parts:
            return prefix, kind, Path(*rel.parts[len(base.parts) :])
    return None


def load() -> tuple[list[Spec], list[str]]:
    """Parse every spec file and return the specs and the errors of the file layout."""
    specs: list[Spec] = []
    errors: list[str] = []
    for path in sorted(SPECS.rglob("*.md")):
        rel = path.relative_to(SPECS)
        if rel.parent == Path("."):
            continue
        kind = _kind_of(rel)
        if kind is None:
            errors.append(f"{rel}: not below a kind folder (000010)")
            continue
        prefix, _, below = kind
        if len(below.parts) != 3:
            errors.append(f"{rel}: must be <area>/<topic>/<file> below the kind folder (000010)")
            continue
        if not FILE_NAME.match(path.name):
            errors.append(f"{rel}: file name breaks 000033")
        for folder in below.parts[:2]:
            if not FOLDER.match(folder):
                errors.append(f"{rel}: folder {folder!r} breaks 000011")
        parsed = _parse_front_matter(path.read_text(encoding="utf-8"))
        if parsed is None:
            errors.append(f"{rel}: no front matter (000002)")
            continue
        meta, keys, body = parsed
        full_id = f"{prefix}/{below.parts[0]}/{below.parts[1]}/{path.name[:6]}"
        specs.append(Spec(path, full_id, meta, keys, body))
    return specs, errors


def _check_meta(spec: Spec, ids: dict[str, Spec]) -> list[str]:
    """Check the front matter of one spec."""
    rel = spec.path.relative_to(SPECS)
    errors: list[str] = []
    meta = spec.meta
    order = [k for k in KEYS if k in spec.keys]
    if spec.keys != order or set(spec.keys) - set(KEYS) or REQUIRED - set(spec.keys):
        errors.append(f"{rel}: front matter keys or their order break 000002: {spec.keys}")
    raw_id = spec.path.read_text(encoding="utf-8").split("\n", 2)[1]
    if raw_id != f'id: "{spec.path.name[:6]}"':
        errors.append(f"{rel}: id must be the quoted number of the file name (000002)")
    kind = _kind_of(spec.path.relative_to(SPECS))
    if kind is not None and meta.get("kind") != kind[1]:
        errors.append(f"{rel}: kind {meta.get('kind')!r} does not match the folder (000010)")
    status = meta.get("status")
    if status not in STATUSES:
        errors.append(f"{rel}: status {status!r} breaks 000003")
    if not isinstance(meta.get("updated"), str) or not DATE.match(str(meta.get("updated"))):
        errors.append(f"{rel}: updated must be YYYY-MM-DD (000002)")
    replaced_by = meta.get("replaced_by")
    if (status == "replaced") != (replaced_by is not None):
        errors.append(f"{rel}: replaced_by goes with status replaced only (000002)")
    if isinstance(replaced_by, str):
        target = ids.get(replaced_by)
        if not FULL_ID.match(replaced_by) or target is None:
            errors.append(f"{rel}: replaced_by {replaced_by!r} is no full ID of a spec (000002)")
        elif target.meta.get("status") in ("replaced", "removed"):
            errors.append(f"{rel}: replaced_by points to a rule that is not in force")
    tests = meta.get("tests", [])
    for entry in tests if isinstance(tests, list) else [tests]:
        if not TEST_ENTRY.match(entry) or not (ROOT / entry.split(":")[0]).is_file():
            errors.append(f"{rel}: tests entry {entry!r} names no test file (000002)")
    scope = meta.get("scope")
    if not isinstance(scope, list) or not scope:
        errors.append(f"{rel}: scope must be a list of paths (000002)")
    else:
        for entry in scope:
            if not (ROOT / entry).exists():
                errors.append(f"{rel}: scope path {entry!r} does not exist (000002)")
        if len(set(scope)) != len(scope):
            errors.append(f"{rel}: scope lists a path two times")
    return errors


def _check_body(spec: Spec) -> list[str]:
    """Check the heading, the labels and `must` of one spec."""
    rel = spec.path.relative_to(SPECS)
    errors: list[str] = []
    headings = [line for line in spec.body.splitlines() if line.startswith("#")]
    if headings != [f"# {spec.meta.get('title')}"]:
        errors.append(f"{rel}: the body must have one # heading equal to the title (000004)")
    labels = LABEL.findall(spec.body)
    if labels not in ([], ["Reason"], ["Test"], ["Reason", "Test"]):
        errors.append(f"{rel}: labels must be Reason, then Test, once each (000008)")
    rule_text = LABEL.split(spec.body, maxsplit=1)[0]
    if spec.meta.get("status") in ("draft", "approved") and not MUST.search(rule_text):
        errors.append(f"{rel}: the rule text has no must or must not (000018)")
    return errors


def _index(specs: list[Spec]) -> str:
    """Return the index table of README.md."""
    rows = [
        f"| [{s.full_id}]({s.path.relative_to(SPECS).as_posix()}) | {s.meta.get('title')} "
        f"| {s.meta.get('status')} |"
        for s in sorted(specs, key=lambda s: s.full_id)
    ]
    return "\n".join(["| ID | Title | Status |", "| --- | --- | --- |", *rows]) + "\n"


def _tree() -> str:
    """Return the tree block of README.md from the folders."""
    lines = ["specs/"]
    for top in ("style", "requirements"):
        lines.append(f"  {top}/")
        if top == "style":
            groups = [("", SPECS / "style", "    ")]
        else:
            groups = [
                (f"    {k}/", SPECS / "requirements" / k, "      ")
                for k in ("functional", "non-functional")
            ]
        for head, base, indent in groups:
            if head:
                lines.append(head)
            areas = sorted(p for p in base.iterdir() if p.is_dir())
            width = max(len(a.name) for a in areas) + 2
            for area in areas:
                topics = ", ".join(sorted(t.name for t in area.iterdir() if t.is_dir()))
                lines.append(f"{indent}{(area.name + '/').ljust(width)} {topics}")
    return "\n".join(lines) + "\n"


def _readme(specs: list[Spec]) -> str:
    """Return README.md with a current tree and index."""
    text = README.read_text(encoding="utf-8")
    text = re.sub(r"```\nspecs/\n.*?```", lambda _: f"```\n{_tree()}```", text, flags=re.S)
    head = text[: text.index(INDEX_START) + len(INDEX_START)]
    return f"{head}\n{_index(specs)}"


def _section_refs(ids: dict[str, Spec]) -> list[str]:
    """Return the `§` references in the code that name no spec (000032)."""
    errors: list[str] = []
    for folder in CODE_DIRS:
        for path in (ROOT / folder).rglob("*"):
            if path.suffix not in CODE_SUFFIXES or "node_modules" in path.parts:
                continue
            for ref in SECTION_REF.findall(path.read_text(encoding="utf-8", errors="ignore")):
                if ref not in ids:
                    errors.append(f"{path.relative_to(ROOT)}: §{ref} names no spec (000032)")
    return errors


def main(argv: list[str]) -> int:
    """Run every check. Return 1 when one fails."""
    specs, errors = load()
    ids = {s.full_id: s for s in specs}
    numbers: dict[str, Path] = {}
    for spec in specs:
        number = spec.path.name[:6]
        if number in numbers:
            errors.append(f"{spec.path.relative_to(SPECS)}: number used by {numbers[number]} (000006)")
        numbers[number] = spec.path.relative_to(SPECS)
        errors += _check_meta(spec, ids)
        errors += _check_body(spec)
    if "--write" in argv:
        README.write_text(_readme(specs), encoding="utf-8")
    elif README.read_text(encoding="utf-8") != _readme(specs):
        errors.append("README.md: index or tree is not current; run with --write (000013)")
    errors += _section_refs(ids)
    for error in errors:
        print(error)
    print(f"{len(specs)} specs, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
