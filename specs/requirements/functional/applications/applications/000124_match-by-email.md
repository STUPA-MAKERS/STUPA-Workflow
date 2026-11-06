---
id: "000124"
title: A guest e-mail of an active account becomes that account
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications/service/on_behalf.py
  - backend/app/modules/applications/service/create.py
  - frontend/src/app/pages/applications/capture/application-capture.component.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A guest e-mail of an active account becomes that account

If the guest e-mail of a capture belongs to an active account (case-insensitive), the Antrag
must belong to that account. The UI must show "Zu dieser E-Mail gibt es ein Konto: <Name>". The
audit entry must have `matchedByEmail`.
