---
id: "001650"
title: A forced status needs a reason from a list
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/flow/schemas.py
  - backend/app/modules/flow/service.py
  - frontend/src/app/pages/applications/force-status-dialog/force-status-dialog.component.ts
scope:
  - backend/app/modules/flow
  - frontend/src/app/pages/applications
---

# A forced status needs a reason from a list

The dialog `Status erzwingen` (`Force status`) must ask for a reason from this list:

- `Beschluss außerhalb der Plattform` (`Decision outside the platform`),
- `Fehlbedienung Antragsteller:in` (`Applicant error`),
- `Korrektur eines Fehlers` (`Correction of an error`),
- `Sonstiges` (`Other`).

The reason is required. For `Sonstiges` a text of at least 10 characters after trimming is
required. For the other reasons the text is optional. The server must refuse a request without
a reason, and a request with `Sonstiges` and a shorter text, with 422. The audit entry and the
status event must store the reason key and the text.

Reason: Prod data holds 82 forced changes, and 33 of them have the note `.`. Nobody can see which ways the flow does not have.

Test: A backend unit test refuses a missing reason and a short text for `Sonstiges`, and stores the reason key.
