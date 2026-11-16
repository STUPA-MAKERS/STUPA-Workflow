#!/usr/bin/env python3
"""Validate the schema files and the examples of the protocol specs in `specs/protocols/`.

`scripts/check_specs.py` checks the form of a protocol spec with the standard library only.
This script needs `jsonschema-rs` from the backend dev dependencies. It checks that every
schema file is a valid JSON Schema 2020-12 (000958) and that every `json` code block of
`## Example` matches the schema of its spec (000959).

Usage:
    python3 scripts/check_protocols.py    check, exit 1 on a violation
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import jsonschema_rs

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_specs import SPECS, Spec, is_json_media, load, schema_path

JSON_BLOCK = re.compile(r"^```json\n(.*?)^```", re.MULTILINE | re.DOTALL)
EXAMPLE = re.compile(r"^## Example\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def check(spec: Spec) -> list[str]:
    """Check the schema file and the examples of one protocol spec."""
    rel = spec.path.relative_to(SPECS)
    schema_file = schema_path(spec.path)
    if not is_json_media(spec.meta.get("media_type")) or not schema_file.is_file():
        return []
    try:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        jsonschema_rs.meta.validate(schema)
    except (json.JSONDecodeError, jsonschema_rs.ValidationError) as error:
        return [f"{rel}: {schema_file.name} is no valid JSON Schema 2020-12: {error} (000958)"]
    validator = jsonschema_rs.validator_for(schema, validate_formats=True)
    section = EXAMPLE.search(spec.body)
    blocks = JSON_BLOCK.findall(section.group(1)) if section else []
    if not blocks:
        return [f"{rel}: ## Example has no json code block (000959)"]
    errors: list[str] = []
    for number, block in enumerate(blocks, start=1):
        try:
            instance = json.loads(block)
        except json.JSONDecodeError as error:
            errors.append(f"{rel}: example {number} is no JSON: {error} (000959)")
            continue
        errors += [
            f"{rel}: example {number} at /{'/'.join(map(str, e.instance_path))}: {e.message} "
            "(000959)"
            for e in validator.iter_errors(instance)
        ]
    return errors


def main() -> int:
    """Check every protocol spec. Return 1 when one fails."""
    specs, _ = load()
    protocols = [s for s in specs if s.full_id.startswith("P/")]
    errors = [error for spec in protocols for error in check(spec)]
    for error in errors:
        print(error)
    print(f"{len(protocols)} protocol specs, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
