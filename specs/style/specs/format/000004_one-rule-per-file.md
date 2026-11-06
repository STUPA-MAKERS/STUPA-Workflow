---
id: "000004"
title: One file holds one rule
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - specs/
scope:
  - specs/
---

# One file holds one rule

One spec file must hold exactly one rule. After the front matter come one `#` title, the rule
text and the labels. A spec must not use other headings.

Reason: The rule ID then points to exactly one file.

Test: `scripts/check_specs.py`: the body has exactly one heading, and it equals the title.
