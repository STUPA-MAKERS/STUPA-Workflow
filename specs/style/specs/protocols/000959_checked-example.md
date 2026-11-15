---
id: "000959"
title: The example of a JSON format matches its schema
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - scripts/check_specs.py
  - scripts/check_protocols.py
scope:
  - specs/
---

# The example of a JSON format matches its schema

The `## Example` section of a protocol spec must hold at least one complete example in a fenced
code block. For a JSON format, every `json` code block in `## Example` must match the schema
file. Other code blocks, for example the headers of a request in an `http` block, are not
checked.

Reason: A receiver copies the example first. An example that CI checks cannot drift from the
schema.

Test: `scripts/check_protocols.py` validates every `json` code block of `## Example` against
the schema file. The CI job `specs` runs it.
