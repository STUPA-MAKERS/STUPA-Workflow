---
id: "000960"
title: A breaking change of a format is a new protocol spec
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - scripts/check_specs.py
scope:
  - specs/
---

# A breaking change of a format is a new protocol spec

`version` must be a whole number from 1. A compatible change must change the spec in place and
must keep `version`. A breaking change must be a new protocol spec with a new number and
`version` plus one. The old spec must then get `status: replaced` and `replaced_by` with the new
ID, when the platform no longer sends or reads the old format.

Only these changes are compatible:

- A new optional key in an object.
- A new value in a list of values, if `## Compatibility` tells the receiver to ignore an unknown
  value.

Every other change is a breaking change, for example a removed or renamed key, a new required
key, a new type, a new header or a change of the signature.

Reason: The number is the identity of a rule (000006). A receiver that names the ID of a format
must find the same contract later. While both versions are in force, both specs stay readable.

Test: Review. `scripts/check_specs.py` checks the form of `version`.
