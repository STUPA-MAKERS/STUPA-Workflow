---
id: "NNNNNN"
title: Short title of the format
kind: protocol
status: draft
owner: frederikbeimgraben
updated: YYYY-MM-DD
version: 1
media_type: application/json
tests:
  - "backend/tests/unit/protocols/test_example.py:test_example_matches_schema"
implementation:
  - backend/app/modules/example
scope:
  - backend/app/modules/example
---

# Short title of the format

The rule in one to three sentences: who sends the format, who reads it, and when. Use `must` and
`must not`.

## Transport

| Part | Value |
| --- | --- |
| Medium | HTTP, WebSocket, file or mail. |
| Direction | Who sends, who reads. |
| Address | Path, channel or file name. |
| Headers | The headers and their values. |
| Authentication | How the receiver knows the sender. |

## Schema

The body must match `NNNNNN_<name>.schema.json` (JSON Schema 2020-12). A format that is not
JSON has no schema file and has a table of its parts here.

## Example

```json
{}
```

## Compatibility

A receiver must ignore a key that it does not know.

Reason: The cause of the rule.

Test: The test that validates the output of the code against the schema.
