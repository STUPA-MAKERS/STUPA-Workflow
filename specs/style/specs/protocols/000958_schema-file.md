---
id: "000958"
title: A JSON format has a JSON Schema file beside its spec
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - scripts/check_specs.py
  - scripts/check_protocols.py
scope:
  - specs/
---

# A JSON format has a JSON Schema file beside its spec

A protocol spec with the media type `application/json` or a `+json` media type must have a schema
file beside it. The schema file must have the name of the spec file with `.schema.json` instead
of `.md`, for example `000963_webhook-delivery.schema.json`. The schema must use JSON Schema
2020-12 and must set `$schema` to `https://json-schema.org/draft/2020-12/schema`.

A person writes the schema file. A script must not write it from the code.

A format that is not JSON, for example ICS, XLSX or an archive, must not have a schema file. Its
`## Schema` section must hold a table of its parts.

Every `.json` file below `specs/protocols/` must be the schema file of a protocol spec.

Reason: The schema exists before the code (000226). One schema language lets one validator check
every example and every implementation.

Test: `scripts/check_specs.py` checks the file and `$schema`. `scripts/check_protocols.py`
checks that the schema is a valid JSON Schema 2020-12.
