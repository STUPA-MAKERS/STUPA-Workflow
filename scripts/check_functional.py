#!/usr/bin/env python3
"""Count the functional style violations per file and hold them under a baseline.

The rules are the specs in `specs/style/shared/functional/` (§ S/shared/functional/000437).
The Python part reads the AST of `backend/app`, `backend/worker`, `mcp/` and `typst/` and counts
per file:

- `rebind` (000083): a second assignment to a local name, and every augmented assignment.
- `mutate` (000084): a mutating method call or a subscript write or `del` on a local name.
- `chain` (000086): an `if`/`elif` chain with three or more branches.
- `dataclass` (000087): a `@dataclass` without `frozen=True`.
- `pydantic` (000087): a Pydantic model that is not frozen, neither by its own `frozen=True`
  nor by a frozen base.

The exceptions of 000089 are skipped: tests, migrations, SQLAlchemy ORM rows (a class with a
base `Base`) and Pydantic validators. A parameter is not a local, so a write through a parameter
(`session.add`) does not count. A loop that only causes effects stays a `for` statement and is
not counted.

The frontend part reads an ESLint JSON report (`npx eslint . -f json`) and counts the warnings of
the `functional/*` rules and of `prefer-const`, `no-param-reassign` and
`@typescript-eslint/switch-exhaustiveness-check` per file.

The baseline is one JSON file per area in `scripts/functional-baseline/` (one area per backend
module, per frontend feature folder, and so on), so two pull requests on two areas never touch
the same baseline file. A count above its baseline fails. A count below its baseline fails too,
until the baseline is lowered with `--write`, so the baseline always shows the real count.

It needs only the Python standard library.

Usage:
    python3 scripts/check_functional.py                         check the Python files
    python3 scripts/check_functional.py --eslint report.json    check the frontend report
    python3 scripts/check_functional.py --write [--eslint …]    write the baseline, then check
    python3 scripts/check_functional.py --area modules-voting   limit the run to one area
    python3 scripts/check_functional.py --list                  print the count of each file
"""

from __future__ import annotations

import argparse
import ast
import itertools
import json
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "functional-baseline"
PY_ROOTS = ("backend/app", "backend/worker", "mcp/antragsplattform_mcp", "typst/typst_service")
SKIP_PARTS = frozenset({"tests", "migrations", "__pycache__", ".venv", "vendor"})
MUTATORS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "add",
        "update",
        "pop",
        "popitem",
        "remove",
        "discard",
        "clear",
        "setdefault",
        "sort",
        "reverse",
        "difference_update",
        "intersection_update",
        "symmetric_difference_update",
    }
)
VALIDATORS = frozenset({"field_validator", "model_validator", "validator", "root_validator"})
PYDANTIC_ROOTS = frozenset({"BaseModel", "BaseSettings", "RootModel"})
ESLINT_RULES = frozenset(
    {"prefer-const", "no-param-reassign", "@typescript-eslint/switch-exhaustiveness-check"}
)


@dataclass(frozen=True, slots=True)
class ClassInfo:
    """What the check knows about one class definition."""

    bases: tuple[str, ...]
    frozen: bool


def _name(node: ast.expr) -> str:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=attr):
            return attr
        case ast.Subscript(value=value):
            return _name(value)
        case ast.Call(func=func):
            return _name(func)
        case _:
            return ""


def _frozen_keyword(keywords: Iterable[ast.keyword]) -> bool:
    return any(
        k.arg == "frozen" and isinstance(k.value, ast.Constant) and k.value.value is True
        for k in keywords
    )


def _config_frozen(body: Iterable[ast.stmt]) -> bool:
    return any(
        isinstance(stmt, ast.Assign | ast.AnnAssign)
        and isinstance(stmt.value, ast.Call)
        and _name(stmt.value.func) in {"ConfigDict", "SettingsConfigDict"}
        and _frozen_keyword(stmt.value.keywords)
        for stmt in body
    )


def _class_info(node: ast.ClassDef) -> ClassInfo:
    return ClassInfo(
        bases=tuple(_name(b) for b in node.bases),
        frozen=_frozen_keyword(node.keywords) or _config_frozen(node.body),
    )


def python_files() -> tuple[Path, ...]:
    """Return every Python file the check reads, sorted."""
    return tuple(
        sorted(
            path
            for root in PY_ROOTS
            for path in (ROOT / root).rglob("*.py")
            if not SKIP_PARTS & set(path.relative_to(ROOT).parts)
        )
    )


def _classes(trees: Mapping[Path, ast.Module]) -> dict[str, list[ClassInfo]]:
    pairs = sorted(
        (
            (node.name, _class_info(node))
            for tree in trees.values()
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        ),
        key=lambda pair: pair[0],
    )
    return {
        name: [info for _, info in group]
        for name, group in itertools.groupby(pairs, key=lambda pair: pair[0])
    }


def _is_pydantic(name: str, classes: Mapping[str, list[ClassInfo]], seen: frozenset[str]) -> bool:
    return name in PYDANTIC_ROOTS or (
        name not in seen
        and any(
            _is_pydantic(base, classes, seen | {name})
            for info in classes.get(name, ())
            for base in info.bases
        )
    )


def _is_frozen(name: str, classes: Mapping[str, list[ClassInfo]], seen: frozenset[str]) -> bool:
    return name not in seen and any(
        info.frozen or any(_is_frozen(base, classes, seen | {name}) for base in info.bases)
        for info in classes.get(name, ())
    )


def _orm_row(node: ast.ClassDef) -> bool:
    return any(_name(b) in {"Base", "DeclarativeBase"} for b in node.bases)


def _validator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_name(d) in VALIDATORS for d in node.decorator_list)


def _own_nodes(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """Yield the nodes of a function body without the nested functions and classes.

    An explicit stack walk is the readable form of this traversal, so it stays imperative.
    """
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            stack.extend(ast.iter_child_nodes(node))


def _targets(node: ast.AST) -> tuple[str, ...]:
    match node:
        case ast.Assign(targets=targets):
            return tuple(n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name))
        case ast.AnnAssign(target=ast.Name(id=name), value=value) if value is not None:
            return (name,)
        case ast.NamedExpr(target=ast.Name(id=name)):
            return (name,)
        case _:
            return ()


def _function_counts(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Counter[str]:
    nodes = tuple(_own_nodes(func))
    bound = Counter(name for node in nodes for name in _targets(node))
    local = frozenset(bound)
    rebinds = sum(n - 1 for n in bound.values()) + sum(isinstance(n, ast.AugAssign) for n in nodes)
    mutations = sum(
        1
        for node in nodes
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MUTATORS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in local
        )
        or (
            isinstance(node, ast.Assign | ast.Delete)
            and any(
                isinstance(t, ast.Subscript)
                and isinstance(t.value, ast.Name)
                and t.value.id in local
                for t in node.targets
            )
        )
    )
    return Counter({"rebind": rebinds, "mutate": mutations})


def _chain_length(node: ast.If) -> int:
    match node.orelse:
        case [ast.If() as nested]:
            return 1 + _chain_length(nested)
        case []:
            return 1
        case _:
            return 2


def _chains(tree: ast.Module) -> int:
    elif_heads = frozenset(
        id(child)
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        for child in node.orelse
        if len(node.orelse) == 1 and isinstance(child, ast.If)
    )
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and id(node) not in elif_heads and _chain_length(node) >= 3
    )


def _file_counts(tree: ast.Module, classes: Mapping[str, list[ClassInfo]]) -> Counter[str]:
    orm_functions = frozenset(
        id(item)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _orm_row(node)
        for item in ast.walk(node)
    )
    functions = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and id(node) not in orm_functions
        and not _validator(node)
    )
    class_nodes = tuple(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    dataclasses = sum(
        1
        for node in class_nodes
        for d in node.decorator_list
        if _name(d) == "dataclass"
        and not (isinstance(d, ast.Call) and _frozen_keyword(d.keywords))
    )
    pydantic = sum(
        1
        for node in class_nodes
        if _is_pydantic(node.name, classes, frozenset())
        and node.name not in PYDANTIC_ROOTS
        and not _is_frozen(node.name, classes, frozenset())
    )
    return sum(
        (_function_counts(f) for f in functions),
        Counter({"chain": _chains(tree), "dataclass": dataclasses, "pydantic": pydantic}),
    )


def python_counts() -> dict[str, int]:
    """Return the violation count of every Python file that has one."""
    trees = {path: ast.parse(path.read_text(), str(path)) for path in python_files()}
    classes = _classes(trees)
    totals = {
        str(path.relative_to(ROOT)): sum(_file_counts(tree, classes).values())
        for path, tree in trees.items()
    }
    return {path: n for path, n in totals.items() if n}


def eslint_counts(report: Path) -> dict[str, int]:
    """Return the functional warning count per file of an ESLint JSON report."""
    entries = json.loads(report.read_text())
    totals = {
        str(Path(entry["filePath"]).resolve().relative_to(ROOT)): sum(
            1
            for message in entry["messages"]
            if (message.get("ruleId") or "").startswith("functional/")
            or message.get("ruleId") in ESLINT_RULES
        )
        for entry in entries
    }
    return {path: n for path, n in totals.items() if n}


def area(path: str) -> str:
    """Return the baseline area of a file, one per module or feature folder."""
    parts = Path(path).parts
    match parts:
        case ("backend", "app", "modules", module, *_):
            return f"backend-{module}"
        case ("backend", "app", "shared", *_):
            return "backend-shared"
        case ("backend", *_):
            return "backend-core"
        case ("frontend", "src", "app", group, folder, _, *_):
            return f"frontend-{group}-{folder}"
        case ("frontend", *_):
            return "frontend-core"
        case (top, *_):
            return top
        case _:
            return "root"


def _grouped(counts: Mapping[str, int]) -> dict[str, dict[str, int]]:
    areas = sorted({area(path) for path in counts})
    return {a: {p: n for p, n in sorted(counts.items()) if area(p) == a} for a in areas}


def _frontend(name: str) -> bool:
    return name.startswith("frontend")


def load_baseline(frontend: bool) -> dict[str, dict[str, int]]:
    """Return the stored baseline of the Python areas or of the frontend areas."""
    return {
        path.stem: json.loads(path.read_text())
        for path in sorted(BASELINE.glob("*.json"))
        if _frontend(path.stem) == frontend
    }


def write_baseline(counts: Mapping[str, int], frontend: bool) -> None:
    """Replace the baseline files of the Python areas or of the frontend areas."""
    BASELINE.mkdir(exist_ok=True)
    for path in BASELINE.glob("*.json"):
        if _frontend(path.stem) == frontend:
            path.unlink()
    for name, files in _grouped(counts).items():
        (BASELINE / f"{name}.json").write_text(json.dumps(files, indent=2) + "\n")


def compare(
    counts: Mapping[str, int], baseline: Mapping[str, Mapping[str, int]], only: str | None
) -> tuple[str, ...]:
    """Return one message for each file whose count differs from its baseline."""
    stored = {p: n for files in baseline.values() for p, n in files.items()}
    paths = sorted(
        p for p in set(counts) | set(stored) if only is None or area(p) == only
    )
    return tuple(
        f"{p}: {counts.get(p, 0)} violations, baseline {stored.get(p, 0)}"
        + (
            " (the count went up: fix the new violations)"
            if counts.get(p, 0) > stored.get(p, 0)
            else " (the count went down: run with --write to lower the baseline)"
        )
        for p in paths
        if counts.get(p, 0) != stored.get(p, 0)
    )


def main(argv: list[str]) -> int:
    """Run the check and return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--eslint", type=Path, help="ESLint JSON report of the frontend")
    parser.add_argument("--write", action="store_true", help="write the baseline first")
    parser.add_argument("--area", help="check one area only")
    parser.add_argument("--list", action="store_true", help="print the count of each file")
    args = parser.parse_args(argv)
    frontend = args.eslint is not None
    counts = eslint_counts(args.eslint) if frontend else python_counts()
    if args.list:
        for path, n in sorted(counts.items(), key=lambda item: -item[1]):
            print(f"{n:5d} {path}")
    if args.write:
        write_baseline(counts, frontend)
    problems = compare(counts, load_baseline(frontend), args.area)
    for problem in problems:
        print(problem)
    print(f"{sum(counts.values())} functional style violations in {len(counts)} files")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
