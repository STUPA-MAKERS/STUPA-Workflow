---
id: "003007"
title: The signature lines of the protocol PDF are a setting of the Gremium
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/unit/modules/protocol/test_protocol_markdown.py:signature"
implementation:
  - backend/app/modules/gremien/models.py
  - backend/app/modules/protocol/markdown.py
  - frontend/src/app/pages/admin
scope:
  - backend/app/modules/gremien
  - backend/app/modules/protocol
  - frontend/src/app/pages/admin
  - mcp
---

# The signature lines of the protocol PDF are a setting of the Gremium

A Gremium must hold a list of signature lines for its protocol PDF, for example "Schriftführung"
and "Vorstand". The protocol PDF must end with exactly these lines, in this order. The page of the
Gremium must show the list next to the protocol settings, and the person can add, edit, move and
remove a line. The code must not hold a line. An empty list gives a protocol without signature
lines.

The migration must give each existing Gremium the two lines that the PDF shows today, so an
existing protocol does not change. A new Gremium starts with an empty list.

Reason: Who signs a protocol depends on the rules of order of one Gremium.

Test: A unit test of the protocol Markdown writes the configured lines in order and no line for an
empty list. An integration test of the admin API saves and reads back the lines.
