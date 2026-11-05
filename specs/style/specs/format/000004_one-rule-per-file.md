---
id: S/specs/format/000004
title: One file holds one rule
kind: style
status: draft
scope:
  - specs/
owner: frederikbeimgraben
updated: 2026-11-05
---

# One file holds one rule

One spec file holds exactly one rule. After the preamble comes one `#` title, then the rule
text, then the labels. Do not use other headings.

Reason: The rule ID then points to exactly one file.

Test: The body has exactly one heading, and it is a `#` heading.
