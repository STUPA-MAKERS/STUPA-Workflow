---
id: "001663"
title: The timeline and the audit show the old and the new Antragsart
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The timeline and the audit show the old and the new Antragsart

A change of the Antragsart (001660) must add a timeline entry `Antragsart geändert`
(`Application type changed`) with the old and the new Antragsart. It must write an audit entry
with the old and the new Antragsart.

Reason: A change of the Antragsart changes the form and the later flow guards, so every reader must see it.

Test: A backend unit test checks the timeline entry and the audit entry.
