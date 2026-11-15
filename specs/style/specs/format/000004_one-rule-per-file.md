---
id: "000004"
title: One file holds one rule
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - scripts/check_specs.py
scope:
  - specs/
---

# One file holds one rule

One spec file must hold exactly one rule. After the front matter come one `#` title, the rule
text and the labels. A spec must not use other headings. A protocol spec holds one whole format
and has the fixed `##` sections of 000957.

Reason: The rule ID then points to exactly one file.

Test: `scripts/check_specs.py`: the body has exactly one heading, and it equals the title. A
protocol spec has the title and the sections of 000957.
