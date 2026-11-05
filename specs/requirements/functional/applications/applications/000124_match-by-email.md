---
id: "000124"
title: A guest e-mail of an active account becomes that account
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A guest e-mail of an active account becomes that account

If the guest e-mail of a capture belongs to an active account (case-insensitive), the Antrag
belongs to that account. The UI shows "Zu dieser E-Mail gibt es ein Konto: <Name>". The audit
entry has `matchedByEmail`.
