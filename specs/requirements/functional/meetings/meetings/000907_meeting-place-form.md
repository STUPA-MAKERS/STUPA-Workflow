---
id: "000907"
title: A meeting has a place and a form
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/livevote/test_public_meeting.py:test_meeting_kind_place_and_form"
implementation:
  - backend/app/modules/meetings/models.py
  - backend/app/modules/livevote/schemas.py
  - backend/app/modules/livevote/service/lifecycle.py
  - frontend/src/app/features/meetings/create-meeting-dialog/create-meeting-dialog.component.html
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# A meeting has a place and a form

A meeting must have the optional text `location` with at most 200 characters. A meeting must
have the form `presence` ("Präsenz"), `hybrid` ("Hybrid") or `video` ("Videokonferenz"), and a
new meeting must start as `presence`.

Reason: The Geschäftsordnung asks the invitation and the protocol to name the place and the
form of the Sitzung.

Test: An integration test that creates a meeting with a place and a form.
