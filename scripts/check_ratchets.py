#!/usr/bin/env python3
"""Hold three counts of the backend under a baseline, so they can only go down.

- `service-commits` (§ S/backend/python/000640): the `commit()` calls per file in `backend/app`
  outside the router files. A router file is `router.py` or `*_router.py`. A service function
  must not commit (000474), because a caller can then put several service calls into one
  transaction. The baseline shows the calls that still have to move to the routers.
- `session-fakes` (§ S/shared/testing/000642): the classes per file in `backend/tests/unit`
  whose name contains `Session`. Such a class stands in for a database session. A new test of a
  query runs on a real Postgres (000641), because a fake session returns the rows that the test
  wrote down, and a wrong `WHERE` then passes.
- `import-exceptions` (§ S/backend/python/000646): the entries of `ignore_imports` per import
  contract in `backend/pyproject.toml`. An entry is an import that breaks the layers of the
  modules (000643) or goes from the shared code into a module (000644). `lint-imports` fails
  for an entry that matches no import, so an entry goes away together with its import.

The baseline is one JSON file per count in `scripts/ratchet-baseline/`, a map from the file path
to its count, or from the id of the contract to its count. A key that is not in the baseline has
the count 0. A count above its baseline
fails. A count below its baseline fails too, until the baseline is lowered with `--write`, so the
baseline always shows the real count. `--write` refuses to raise a count.

It needs only the Python standard library.

Usage:
    python3 scripts/check_ratchets.py            check the counts
    python3 scripts/check_ratchets.py --write    lower the baselines, then check
    python3 scripts/check_ratchets.py --list     print the count of each file or contract
"""

from __future__ import annotations

import ast
import json
import sys
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = ROOT / "scripts" / "ratchet-baseline"
IMPORT_EXCEPTIONS = "import-exceptions"
IMPORT_CONTRACTS = "backend/pyproject.toml"


def _is_router(path: Path) -> bool:
    return path.name == "router.py" or path.name.endswith("_router.py")


def count_commits(tree: ast.AST) -> int:
    """Count the calls of a method `commit` without arguments."""
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
        and not node.args
        and not node.keywords
    )


def count_session_classes(tree: ast.AST) -> int:
    """Count the classes whose name contains `Session`."""
    return sum(
        1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and "Session" in node.name
    )


RATCHETS: Mapping[str, tuple[str, Callable[[Path], bool], Callable[[ast.AST], int]]] = {
    "service-commits": ("backend/app", lambda p: not _is_router(p), count_commits),
    "session-fakes": ("backend/tests/unit", lambda _p: True, count_session_classes),
}

NAMES = (*RATCHETS, IMPORT_EXCEPTIONS)


def count_import_exceptions(pyproject: str) -> dict[str, int]:
    """Count the entries of `ignore_imports` of each import contract, by the contract id."""
    linter = tomllib.loads(pyproject).get("tool", {}).get("importlinter", {})
    contracts = linter.get("contracts", [])
    return {str(c["id"]): len(c.get("ignore_imports", [])) for c in contracts}


def measure(name: str, root: Path = ROOT) -> dict[str, int]:
    """Count one ratchet over its folder or file; a key with the count 0 is left out."""
    if name == IMPORT_EXCEPTIONS:
        found = count_import_exceptions((root / IMPORT_CONTRACTS).read_text(encoding="utf-8"))
        return {contract: n for contract, n in found.items() if n}
    folder, wanted, count = RATCHETS[name]
    counts = {
        path.relative_to(root).as_posix(): count(ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted((root / folder).rglob("*.py"))
        if wanted(path)
    }
    return {path: n for path, n in counts.items() if n}


def compare(name: str, counts: Mapping[str, int], baseline: Mapping[str, int]) -> list[str]:
    """Name each file whose count differs from its baseline."""
    return [
        f"{name}: {path} has {counts.get(path, 0)}, the baseline has {baseline.get(path, 0)}"
        + (
            " (the count went up)"
            if counts.get(path, 0) > baseline.get(path, 0)
            else " (lower the baseline with --write)"
        )
        for path in sorted({*counts, *baseline})
        if counts.get(path, 0) != baseline.get(path, 0)
    ]


def _baseline_path(name: str) -> Path:
    return BASELINE_DIR / f"{name}.json"


def _read(name: str) -> dict[str, int]:
    path = _baseline_path(name)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _write(name: str, counts: Mapping[str, int]) -> list[str]:
    """Write the baseline, unless a count went up against an existing baseline."""
    path = _baseline_path(name)
    old = _read(name)
    raised = [
        f"{name}: {file} went up from {old.get(file, 0)} to {n}, --write does not raise a count"
        for file, n in counts.items()
        if path.is_file() and n > old.get(file, 0)
    ]
    if not raised:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(counts), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return raised


def main(argv: list[str]) -> int:
    """Check, list or write the baselines; exit 1 on a difference."""
    measured = {name: measure(name) for name in NAMES}
    if "--list" in argv:
        for name, counts in measured.items():
            for path, n in counts.items():
                print(f"{name}\t{n}\t{path}")
        return 0
    refused = (
        [line for name in NAMES for line in _write(name, measured[name])]
        if "--write" in argv
        else []
    )
    errors = refused + [
        line for name in NAMES for line in compare(name, measured[name], _read(name))
    ]
    for line in errors:
        print(line, file=sys.stderr)
    totals = ", ".join(f"{name} {sum(counts.values())}" for name, counts in measured.items())
    print(f"{totals}; {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
