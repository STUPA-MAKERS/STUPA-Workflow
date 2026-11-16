"""Validate the output of the code against the schema file of a protocol spec.

§S/specs/protocols/000961: a test of a JSON format builds the format with the code and checks
it with `assert_matches_schema`. The schema file lies beside the spec in `specs/protocols/`
and has the spec number as the start of its name (§S/specs/protocols/000958).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema_rs

SPECS = Path(__file__).resolve().parents[3] / "specs" / "protocols"


def schema_of(number: str) -> dict[str, Any]:
    """Return the schema of the protocol spec with this six-digit number."""
    found = sorted(SPECS.rglob(f"{number}_*.schema.json"))
    if len(found) != 1:
        msg = f"expected one schema file for protocol spec {number}, found {len(found)}"
        raise LookupError(msg)
    data: dict[str, Any] = json.loads(found[0].read_text(encoding="utf-8"))
    return data


def assert_matches_schema(number: str, instance: object) -> None:
    """Fail with every schema error when `instance` does not match the schema."""
    validator = jsonschema_rs.validator_for(schema_of(number), validate_formats=True)
    errors = [
        f"{'/'.join(map(str, error.instance_path))}: {error.message}"
        for error in validator.iter_errors(instance)
    ]
    assert not errors, f"protocol spec {number}: " + "; ".join(errors)
