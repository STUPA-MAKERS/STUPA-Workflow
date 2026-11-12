---
id: "000746"
title: An observer reads the Antrag and does not change it
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation:
  - backend/app/modules/applications
scope:
  - backend/app/modules/applications
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# An observer reads the Antrag and does not change it

An observer must read the Antrag in the applicant view (`F/applications/applications/000127`):
the status, the history, the answers, the attachments and the public comments. An observer must
not edit the Antrag, fire a transition, upload a file or write a comment.

An observer must reach the Antrag in two ways:

- logged in with an account whose e-mail is the observer address, compared case-insensitively,
- with the e-mail login of the observer address (`F/administration/accounts/000583`).

The list "Meine Anträge" and the Anträge page must show an observed Antrag with the label
"Beobachtet".

Reason: An observer follows the Antrag. The applicant stays the only person who acts for it.

Test: `backend/tests/integration/modules/applications/test_observers.py`: an account and an
e-mail session of the observer address read the Antrag, and get 403 for an edit, a transition,
an upload and a comment.
