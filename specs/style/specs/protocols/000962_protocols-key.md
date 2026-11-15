---
id: "000962"
title: A rule names the formats that it uses
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - scripts/check_specs.py
scope:
  - specs/
---

# A rule names the formats that it uses

A functional or non-functional spec that sends, reads or stores a format of a protocol spec must
list the full ID of that protocol spec in `protocols`. A spec that uses no such format must not
have the key `protocols`. Each entry must be the ID of a protocol spec that is in force.

Reason: A reader of a rule finds the exact format that the rule uses. A tool finds every rule
that a format change affects.

Test: `scripts/check_specs.py` checks every entry of `protocols`.
