"""Write and check the UML data of the app in `specs/uml/` (§S/specs/uml/000679-000684).

The script writes three views from the code and checks the hand-written state views:

- `components.json`: the backend modules, their layers and their imports (000681)
- `classes.json`: the database models and their foreign keys (000682)
- `deployment.json`: the services of the compose stack (000683)
- `states/<table>-<column>.json`: written by hand, checked against the database (000684)

It imports the backend, so it runs with the backend dependencies installed:

    python3 scripts/build_uml.py --write  write the generated views, then check every view
    python3 scripts/build_uml.py --check  fail when a view is not current or breaks the format
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy import Column, Table

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
UML = ROOT / "specs" / "uml"
COMPOSE = ROOT / "deploy" / "docker-compose.yml"

SHARED = ("app.shared", "app.db", "app.settings", "app.logging_config")
SHARED_LAYER = 6
IN_LIST = re.compile(r"^\s*\(?\s*(\w+)\s+IN\s*\((.*)\)\s*\)?\s*$", re.IGNORECASE | re.DOTALL)
GENERATED = ("components", "classes", "deployment")

View = dict[str, Any]


def _dump(view: View) -> str:
    """Return the bytes of one view: sorted keys, two spaces of indent, a newline at the end."""
    return json.dumps(view, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _sorted(view: View) -> View:
    """Sort the elements by ID and the edges by their end points."""
    view["elements"] = sorted(view["elements"], key=lambda e: e["id"])
    if "edges" in view:
        view["edges"] = sorted(
            view["edges"], key=lambda e: (e["from"], e["to"], json.dumps(e, sort_keys=True))
        )
    return view


def _rel(path: Path) -> str:
    """Return a path relative to the repository root, with `/`."""
    return path.resolve().relative_to(ROOT).as_posix()


def _backend_on_path() -> None:
    """Make `app` importable from the backend folder."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))


def layers() -> dict[str, int]:
    """Return the layer of each module from the import contract (000643)."""
    data = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    contract = next(c for c in contracts if c["id"] == "module-layers")
    return {
        name.strip(): number
        for number, row in enumerate(contract["layers"], start=1)
        for name in row.split(":")
    }


def _owner(module: str) -> str | None:
    """Return the element ID of a Python module: the module package, `shared` or nothing."""
    parts = module.split(".")
    if parts[:2] == ["app", "modules"] and len(parts) > 2:
        return parts[2]
    if any(module == s or module.startswith(s + ".") for s in SHARED):
        return "shared"
    return None


def components() -> View:
    """Build the component view from the import graph of `lint-imports` (000681)."""
    import grimp

    _backend_on_path()
    graph = grimp.build_graph("app", cache_dir=None)
    layer_of = layers()
    modules = sorted(
        p.name
        for p in (BACKEND / "app" / "modules").iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    )
    elements = [
        {"id": m, "name": m, "path": f"backend/app/modules/{m}", "layer": layer_of.get(m, 0)}
        for m in modules
    ]
    elements.append(
        {"id": "shared", "name": "shared", "path": "backend/app/shared", "layer": SHARED_LAYER}
    )
    counts: Counter[tuple[str, str]] = Counter()
    for importer in graph.modules:
        source = _owner(importer)
        if source is None:
            continue
        for imported in graph.find_modules_directly_imported_by(importer):
            target = _owner(imported)
            if target is None or target == source:
                continue
            details = graph.get_import_details(importer=importer, imported=imported)
            counts[(source, target)] += max(len(details), 1)
    edges = [{"from": a, "to": b, "count": n} for (a, b), n in counts.items()]
    return _sorted(
        {
            "view": "components",
            "title": "Backend modules",
            "elements": elements,
            "edges": edges,
        }
    )


def check_values(table: Table) -> dict[str, list[str]]:
    """Return the values that a check constraint `<column> IN (...)` allows, per column."""
    from sqlalchemy import CheckConstraint

    values: dict[str, list[str]] = {}
    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint):
            continue
        match = IN_LIST.match(str(constraint.sqltext))
        if match:
            values[match.group(1)] = [v.strip().strip("'") for v in match.group(2).split(",")]
    return values


def _type(column: Column[Any]) -> str:
    """Return the SQL type of a column as text."""
    try:
        return str(column.type)
    except Exception:  # a type without a generic compile keeps its class name
        return type(column.type).__name__


def _unique(column: Column[Any]) -> bool:
    """Say whether a column alone is unique: the only primary key column or a unique column."""
    from sqlalchemy import UniqueConstraint

    table = column.table
    if column.unique or (column.primary_key and len(table.primary_key.columns) == 1):
        return True
    return any(
        isinstance(c, UniqueConstraint) and list(c.columns.keys()) == [column.name]
        for c in table.constraints
    )


def classes() -> View:
    """Build the class view from the SQLAlchemy metadata (000682)."""
    _backend_on_path()
    import app.models  # noqa: F401  — fills Base.metadata
    from app.db import Base

    mappers = list(Base.registry.mappers)
    by_table = {m.local_table.name: m.class_.__name__ for m in mappers}
    elements: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for mapper in mappers:
        cls, table = mapper.class_, mapper.local_table
        module_file = Path(sys.modules[cls.__module__].__file__ or "")
        allowed = check_values(table)
        attributes = []
        for column in table.columns:
            attribute: dict[str, Any] = {
                "name": column.name,
                "type": _type(column),
                "nullable": bool(column.nullable),
                "primaryKey": bool(column.primary_key),
            }
            if column.name in allowed:
                attribute["values"] = allowed[column.name]
            attributes.append(attribute)
            edges.extend(
                {
                    "from": cls.__name__,
                    "to": by_table[fk.column.table.name],
                    "column": column.name,
                    "onDelete": (fk.ondelete or "NO ACTION").upper(),
                    "multiplicity": "1" if _unique(column) else "*",
                }
                for fk in column.foreign_keys
                if fk.column.table.name in by_table
            )
        elements.append(
            {
                "id": cls.__name__,
                "name": cls.__name__,
                "path": _rel(module_file),
                "module": cls.__module__.split(".")[2],
                "table": table.name,
                "attributes": attributes,
            }
        )
    return _sorted(
        {
            "view": "classes",
            "title": "Database models",
            "elements": elements,
            "edges": edges,
        }
    )


def _names(value: object) -> list[str]:
    """Return the names of a compose list or mapping (`networks`, `depends_on`)."""
    if isinstance(value, dict | list):
        return sorted(str(name) for name in value)
    return []


def deployment() -> View:
    """Build the deployment view from the compose file (000683)."""
    import yaml

    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    elements: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for name, service in data["services"].items():
        element: dict[str, Any] = {
            "id": name,
            "name": name,
            "path": _rel(COMPOSE),
            "networks": _names(service.get("networks")) or ["default"],
        }
        build = service.get("build")
        if build is not None:
            context = build if isinstance(build, str) else build.get("context", ".")
            element["build"] = _rel(COMPOSE.parent / context)
        elif "image" in service:
            element["image"] = service["image"]
        elements.append(element)
        edges.extend({"from": name, "to": other} for other in _names(service.get("depends_on")))
    return _sorted(
        {
            "view": "deployment",
            "title": "Compose stack",
            "elements": elements,
            "edges": edges,
        }
    )


BUILDERS = {"components": components, "classes": classes, "deployment": deployment}


def check_format(rel: str, view: object) -> list[str]:
    """Return the format errors of one view file (000679)."""
    errors: list[str] = []
    if not isinstance(view, dict):
        return [f"{rel}: the file must hold one JSON object (000679)"]
    errors.extend(
        f"{rel}: key {key!r} is missing (000679)"
        for key in ("view", "title", "elements")
        if key not in view
    )
    ids: list[str] = []
    for element in view.get("elements", []):
        missing = [k for k in ("id", "name", "path") if k not in element]
        if missing:
            errors.append(
                f"{rel}: element {element.get('id')!r} has no {', '.join(missing)} (000679)"
            )
            continue
        ids.append(element["id"])
        if not (ROOT / element["path"]).exists():
            errors.append(
                f"{rel}: path {element['path']!r} of {element['id']!r} does not exist (000679)"
            )
    errors.extend(
        f"{rel}: element ID {i!r} is not unique (000679)" for i, n in Counter(ids).items() if n > 1
    )
    known = set(ids)
    errors.extend(
        f"{rel}: edge {end} {edge.get(end)!r} is no element (000679)"
        for edge in view.get("edges", [])
        for end in ("from", "to")
        if edge.get(end) not in known
    )
    return errors


def check_state(
    rel: str, view: dict[str, Any], allowed: dict[str, dict[str, list[str]]]
) -> list[str]:
    """Return the errors of one hand-written state view (000684)."""
    errors: list[str] = []
    table, column = view.get("table"), view.get("column")
    if not table or not column:
        return [f"{rel}: a state view needs `table` and `column` (000684)"]
    if Path(rel).stem != f"{table}-{column}":
        errors.append(f"{rel}: the file name must be {table}-{column}.json (000684)")
    states = [e["id"] for e in view.get("elements", []) if "id" in e]
    initial = [e["id"] for e in view.get("elements", []) if e.get("initial")]
    if len(initial) != 1:
        errors.append(f"{rel}: exactly one state must have `initial: true` (000684)")
    errors.extend(
        f"{rel}: transition {e.get('from')}->{e.get('to')} needs {key!r} (000684)"
        for e in view.get("edges", [])
        for key in ("trigger", "path")
        if key not in e
    )
    values = allowed.get(table, {}).get(column)
    if values is not None and sorted(values) != sorted(states):
        errors.append(
            f"{rel}: the states {sorted(states)} are not the values {sorted(values)} of the "
            f"check constraint {table}.{column} (000684)"
        )
    return errors


def _allowed_values() -> dict[str, dict[str, list[str]]]:
    """Return the check constraint values of every table."""
    _backend_on_path()
    import app.models  # noqa: F401  — fills Base.metadata
    from app.db import Base

    return {name: check_values(table) for name, table in Base.metadata.tables.items()}


def run(write: bool) -> list[str]:
    """Write (optionally) and check every view; return the errors."""
    errors: list[str] = []
    for name in GENERATED:
        path = UML / f"{name}.json"
        text = _dump(BUILDERS[name]())
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        elif not path.exists() or path.read_text(encoding="utf-8") != text:
            errors.append(f"specs/uml/{name}.json: not current; run with --write (000680)")
    allowed = _allowed_values()
    for path in sorted(UML.rglob("*")):
        rel = _rel(path)
        if path.is_dir():
            continue
        if path.suffix != ".json":
            errors.append(f"{rel}: only JSON files belong in specs/uml (000679)")
            continue
        try:
            view = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: no valid JSON: {exc} (000679)")
            continue
        errors.extend(check_format(rel, view))
        if path.parent.name == "states" and isinstance(view, dict):
            errors.extend(check_state(rel, view, allowed))
    return errors


def main() -> int:
    """Run the script from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the generated views")
    mode.add_argument("--check", action="store_true", help="check every view")
    args = parser.parse_args()
    errors = run(write=args.write)
    for error in errors:
        print(error)
    print(f"specs/uml: {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
