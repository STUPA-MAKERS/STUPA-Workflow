---
id: "000441"
title: The applicant gets a mail about a captured Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications/captured_mail.py
  - backend/app/modules/applications/router.py
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The applicant gets a mail about a captured Antrag

A capture on behalf must send the applicant the mail "Für dich wurde ein Antrag erfasst".
