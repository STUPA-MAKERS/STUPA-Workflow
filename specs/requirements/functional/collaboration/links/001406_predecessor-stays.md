---
id: "001406"
title: The Vorgänger stays its own relation
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/applications/service/links.py
scope:
  - backend/app/modules/applications
  - backend/app/modules/links
---

# The Vorgänger stays its own relation

The Vorgänger of an Antrag (F/applications/applications/000546) must stay in
`application_link` and must not be a row of `link`. `Verknüpft` of an Antrag must show the
Vorgänger and the Folgeanträge as their own rows, as today, together with the links.

Reason: The Vorgänger has rules that a link does not have: one per Antrag, the same
Antragsart, no cycle, the prefill and its history.

Test: A backend unit test sets a Vorgänger and checks that `link` has no row for it.
