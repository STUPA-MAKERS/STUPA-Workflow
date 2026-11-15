---
id: "000957"
title: A protocol spec describes one whole format
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - scripts/check_specs.py
scope:
  - specs/
---

# A protocol spec describes one whole format

A protocol spec must describe one data exchange format as a whole: one message, one payload, one
file or one export. It must not split one format over several specs. Two formats must not share
one spec.

The body must have the `#` title, the rule text and then exactly these `##` sections, in this
order:

| Section | Content |
| --- | --- |
| `## Transport` | The medium, the direction, the address, the headers and the authentication. |
| `## Schema` | The name of the schema file, or the table of a format that is not JSON (000958). |
| `## Example` | At least one complete example in a code block (000959). |
| `## Compatibility` | What a receiver must accept, so that a compatible change does not break it (000960). |

The labels `Reason:` and `Test:` come after the last section.

Reason: A receiver builds against a format as a whole. One file then holds the complete
contract, and the full rule ID points to it.

Test: `scripts/check_specs.py` checks the headings and their order.
