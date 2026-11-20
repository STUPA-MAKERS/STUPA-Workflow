---
id: "001663"
title: The timeline and the audit show the old and the new Antragsart
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "backend/tests/integration/modules/applications/test_type_change.py:test_change_with_missing_fields_sends_back"
implementation:
  - backend/app/modules/applications/service/type_change.py
  - backend/app/modules/applications/router.py
  - backend/app/modules/applications/service/edits.py
  - frontend/src/app/pages/applications/type-change-dialog
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
