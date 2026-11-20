#!/usr/bin/env python3
"""Check the spec files in `specs/` and keep the index in `specs/README.md` current.

The app and ui-kit share one number space (ui-kit:002211). When `PARTNER_SPECS` names a checkout
of the `specs/` folder of ui-kit, the script also checks the numbers against it and resolves
the references with a repository name (ui-kit:002212).

The script checks the rules for specs (`specs/style/specs/`): the file name, the
place in the tree, the front matter (also `implementation`), the heading, the labels, `must` in the rule
text, the scope paths, `replaced_by`, unique numbers, the index, and every `§`
reference in the code. It finds a `§` before a rule in a spec (000032), and a number that
`origin/development` gave to a different spec after the branch left it (000006). For a protocol spec it also checks `version`, `media_type`, the fixed
sections and the schema file, and for a requirement the `protocols` list. It needs only the
Python standard library; `scripts/check_protocols.py` validates the schemas and the examples.

Usage:
    python3 scripts/check_specs.py          check, exit 1 on a violation
    python3 scripts/check_specs.py --write  write the index of specs/README.md, then check
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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
    "protocols": ("P", "protocol"),
}
KEYS = [
    "id",
    "title",
    "kind",
    "status",
    "owner",
    "updated",
    "replaced_by",
    "version",
    "media_type",
    "tests",
    "protocols",
    "implementation",
    "scope",
]
REQUIRED = {"id", "title", "kind", "status", "owner", "updated", "scope"}
STATUSES = {"draft", "approved", "replaced", "removed"}
FILE_NAME = re.compile(r"^[0-9]{6}_[a-z0-9]+(-[a-z0-9]+)*\.md$")
FOLDER = re.compile(r"^[a-z0-9-]+$")
FULL_ID = re.compile(r"^(F|NF|S|P)(/[a-z0-9-]+)+/[0-9]{6}$")
VERSION = re.compile(r"^[1-9][0-9]*$")
MEDIA_TYPE = re.compile(r"^[a-z]+/[a-z0-9.+-]+$")
PROTOCOL_SECTIONS = ["## Transport", "## Schema", "## Example", "## Compatibility"]
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
FENCE = re.compile(r"^```", re.MULTILINE)
TEST_ENTRY = re.compile(r"^[^:\s]+\.(py|ts):[A-Za-z_][A-Za-z0-9_.]*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LABEL = re.compile(r"^(Reason|Test):", re.MULTILINE)
MUST = re.compile(r"\bmust\b")
SECTION_REF = re.compile(r"§ ?(?:([A-Za-z0-9-]+):)?((?:F|NF|S|P)/[a-z0-9/-]+/[0-9]{6})")
REPO = "STUPA-Workflow"
PARTNER = "ui-kit"
SPEC_SECTION_REF = re.compile(r"§ ?(?:[A-Za-z0-9-]+:)?(?:(?:F|NF|S|P)/[a-z0-9/-]+/)?[0-9]{6}\b")
INLINE_CODE = re.compile(r"`[^`\n]*`")
BASE_REF = "origin/development"
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
    errors += _check_protocol_keys(spec, ids)
    tests = meta.get("tests", [])
    for entry in tests if isinstance(tests, list) else [tests]:
        if not TEST_ENTRY.match(entry) or not (ROOT / entry.split(":")[0]).is_file():
            errors.append(f"{rel}: tests entry {entry!r} names no test file (000002)")
    implementation = meta.get("implementation")
    if status in ("draft", "approved"):
        if implementation != "null" and (not isinstance(implementation, list) or not implementation):
            errors.append(f"{rel}: implementation must be a list of paths or null (000002)")
        elif isinstance(implementation, list):
            errors += [
                f"{rel}: implementation path {entry!r} does not exist (000002)"
                for entry in implementation
                if not (ROOT / entry).exists()
            ]
    elif implementation is not None:
        errors.append(f"{rel}: implementation goes with status draft or approved only (000002)")
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


def is_json_media(media_type: object) -> bool:
    """Return True for `application/json` and every `+json` media type (000958)."""
    return media_type == "application/json" or str(media_type).endswith("+json")


def schema_path(spec_path: Path) -> Path:
    """Return the path of the schema file beside a protocol spec (000958)."""
    return spec_path.with_name(spec_path.name[: -len(".md")] + ".schema.json")


def _check_protocol_keys(spec: Spec, ids: dict[str, Spec]) -> list[str]:
    """Check `version`, `media_type`, the area of a protocol spec and `protocols`."""
    rel = spec.path.relative_to(SPECS)
    errors: list[str] = []
    meta = spec.meta
    is_protocol = spec.full_id.startswith("P/")
    for key in ("version", "media_type"):
        if is_protocol and key not in meta:
            errors.append(f"{rel}: a protocol spec must have {key} (000002)")
        if not is_protocol and key in meta:
            errors.append(f"{rel}: {key} goes with kind protocol only (000002)")
    if is_protocol:
        if "version" in meta and not VERSION.match(str(meta["version"])):
            errors.append(f"{rel}: version must be a whole number from 1 (000960)")
        if "media_type" in meta and not MEDIA_TYPE.match(str(meta["media_type"])):
            errors.append(f"{rel}: media_type {meta['media_type']!r} is no media type (000002)")
        area = spec.full_id.split("/")[1]
        if not (SPECS / "requirements" / "functional" / area).is_dir():
            errors.append(f"{rel}: area {area!r} is no area of the functional specs (000010)")
    protocols = meta.get("protocols")
    if protocols is None:
        return errors
    if not spec.full_id.startswith(("F/", "NF/")):
        errors.append(f"{rel}: protocols goes with an F or NF spec only (000962)")
    if not isinstance(protocols, list) or not protocols:
        errors.append(f"{rel}: protocols must be a list of protocol spec IDs (000962)")
        return errors
    for entry in protocols:
        target = ids.get(entry)
        if not entry.startswith("P/") or target is None:
            errors.append(f"{rel}: protocols entry {entry!r} names no protocol spec (000962)")
        elif target.meta.get("status") in ("replaced", "removed"):
            errors.append(f"{rel}: protocols entry {entry!r} is not in force (000962)")
    if len(set(protocols)) != len(protocols):
        errors.append(f"{rel}: protocols lists an ID two times")
    return errors


def _check_protocol_body(spec: Spec) -> list[str]:
    """Check the sections, the example and the schema file of a protocol spec."""
    rel = spec.path.relative_to(SPECS)
    errors: list[str] = []
    headings = [line for line in spec.body.splitlines() if line.startswith("#")]
    if headings != [f"# {spec.meta.get('title')}", *PROTOCOL_SECTIONS]:
        errors.append(
            f"{rel}: the body must have the # title, then {', '.join(PROTOCOL_SECTIONS)} (000957)"
        )
        return errors
    sections = _sections(spec.body)
    if len(FENCE.findall(sections.get("## Example", ""))) < 2:
        errors.append(f"{rel}: ## Example must hold at least one code block (000959)")
    schema = schema_path(spec.path)
    if is_json_media(spec.meta.get("media_type")):
        errors += _check_schema_file(rel, schema)
    else:
        if schema.exists():
            errors.append(f"{rel}: a format that is not JSON has no schema file (000958)")
        if not re.search(r"^\|", sections.get("## Schema", ""), re.MULTILINE):
            errors.append(f"{rel}: ## Schema of a non-JSON format must hold a table (000958)")
    return errors


def _sections(body: str) -> dict[str, str]:
    """Return the text below each `##` heading of a body."""
    parts = re.split(r"^(## .+)$", body, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _check_schema_file(rel: Path, schema: Path) -> list[str]:
    """Check that the schema file of a JSON format exists and names the 2020-12 dialect."""
    if not schema.is_file():
        return [f"{rel}: the schema file {schema.name} is missing (000958)"]
    try:
        data = json.loads(schema.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{rel}: {schema.name} is no JSON: {error} (000958)"]
    if not isinstance(data, dict) or data.get("$schema") != SCHEMA_DIALECT:
        return [f"{rel}: {schema.name} must set $schema to {SCHEMA_DIALECT} (000958)"]
    return []


def _orphan_schemas(specs: list[Spec]) -> list[str]:
    """Return the schema files below `specs/protocols/` without a protocol spec (000958)."""
    owned = {schema_path(s.path) for s in specs if s.full_id.startswith("P/")}
    return [
        f"{path.relative_to(SPECS)}: no protocol spec owns this schema file (000958)"
        for path in sorted((SPECS / "protocols").rglob("*.json"))
        if path not in owned
    ]


def _check_body(spec: Spec) -> list[str]:
    """Check the heading, the labels and `must` of one spec."""
    rel = spec.path.relative_to(SPECS)
    errors: list[str] = []
    if spec.full_id.startswith("P/"):
        errors += _check_protocol_body(spec)
    elif [line for line in spec.body.splitlines() if line.startswith("#")] != [
        f"# {spec.meta.get('title')}"
    ]:
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
    for top in ("style", "requirements", "protocols"):
        if not (SPECS / top).is_dir():
            continue
        lines.append(f"  {top}/")
        if top in ("style", "protocols"):
            groups = [("", SPECS / top, "    ")]
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


def _section_refs(ids: dict[str, Spec], partner: set[str] | None) -> list[str]:
    """Return the `§` references in the code that name no spec (000032, ui-kit:002212).

    A reference without a repository name, or with `STUPA-Workflow:`, must name a spec of the app. A
    reference with `ui-kit:` must name a spec of the kit; it is checked only when
    `PARTNER_SPECS` is set. Any other repository name is an error.
    """
    errors: list[str] = []
    for folder in CODE_DIRS:
        for path in (ROOT / folder).rglob("*"):
            if path.suffix not in CODE_SUFFIXES or "node_modules" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for repo, ref in SECTION_REF.findall(text):
                rel = path.relative_to(ROOT)
                if repo in ("", REPO):
                    if ref not in ids:
                        errors.append(f"{rel}: §{ref} names no spec (000032)")
                elif repo == PARTNER:
                    if partner is not None and ref not in partner:
                        errors.append(f"{rel}: §{repo}:{ref} names no spec of {PARTNER} (ui-kit:002212)")
                else:
                    errors.append(f"{rel}: §{repo}:{ref} names an unknown repository (ui-kit:002212)")
    return errors


def spec_section_refs(body: str) -> list[str]:
    """Return each `§` before a rule in the text of a spec (000032).

    Inline code does not count, because a spec shows the form of a code reference there. A
    `§` before the paragraph of a law has no six-digit number and does not count either.
    """
    return SPEC_SECTION_REF.findall(INLINE_CODE.sub("", body))


def base_collisions(
    local: dict[str, str], base: dict[str, str], fork: dict[str, str]
) -> list[str]:
    """Return an error for each number that the base branch gave to a different spec (000006).

    Each argument maps a number to the path of its spec: in the working tree, on the base
    branch, and at the commit where the branch left the base branch. A number collides when
    the base branch added it after that commit and the working tree has it at another path.
    """
    return [
        f"{path}: number {number} is {base[number]} on {BASE_REF}; give the spec a new number (000006)"
        for number, path in sorted(local.items())
        if number in base and number not in fork and base[number] != path
    ]


def _partner_ids() -> tuple[set[str], dict[str, str]] | None:
    """Return the full IDs and number to path of the kit specs, or None without PARTNER_SPECS."""
    folder = os.environ.get("PARTNER_SPECS")
    if not folder:
        return None
    base = Path(folder)
    ids: set[str] = set()
    numbers: dict[str, str] = {}
    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(base)
        kind = _kind_of(rel)
        if kind is None or not FILE_NAME.match(path.name) or len(kind[2].parts) != 3:
            continue
        below = kind[2]
        ids.add(f"{kind[0]}/{below.parts[0]}/{below.parts[1]}/{path.name[:6]}")
        numbers[path.name[:6]] = rel.as_posix()
    return ids, numbers


def _git_numbers(ref: str) -> dict[str, str] | None:
    """Return number to spec path at a git ref, or None when git cannot read the ref."""
    try:
        out = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref, "--", "specs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    paths = [Path(line) for line in out.splitlines() if FILE_NAME.match(Path(line).name)]
    return {p.name[:6]: p.relative_to("specs").as_posix() for p in paths}


def _base_errors(numbers: dict[str, Path]) -> list[str]:
    """Compare the numbers with the base branch. A checkout without the ref checks nothing."""
    try:
        fork_ref = subprocess.run(
            ["git", "merge-base", "HEAD", BASE_REF],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return []
    base, fork = _git_numbers(BASE_REF), _git_numbers(fork_ref)
    if base is None or fork is None:
        return []
    return base_collisions({n: p.as_posix() for n, p in numbers.items()}, base, fork)


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
        errors += [
            f"{spec.path.relative_to(SPECS)}: a spec refers to a rule without § (000032): {ref}"
            for ref in spec_section_refs(spec.body)
        ]
    errors += _base_errors(numbers)
    partner = _partner_ids()
    if partner is not None:
        errors += [
            f"{numbers[n]}: number {n} is {PARTNER}:{path}; numbers are shared (ui-kit:002211)"
            for n, path in sorted(partner[1].items())
            if n in numbers and numbers[n].as_posix() != path
        ]
    if "--write" in argv:
        README.write_text(_readme(specs), encoding="utf-8")
    elif README.read_text(encoding="utf-8") != _readme(specs):
        errors.append("README.md: index or tree is not current; run with --write (000013)")
    errors += _orphan_schemas(specs)
    errors += _section_refs(ids, partner[0] if partner else None)
    for error in errors:
        print(error)
    print(f"{len(specs)} specs, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
