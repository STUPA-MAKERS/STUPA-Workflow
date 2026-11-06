---
id: "000376"
title: An anonymization removes every copy of personal data
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications/service/anonymize.py
scope:
  - backend/app/modules/applications
  - backend/app/modules/privacy
---

# An anonymization removes every copy of personal data

An anonymization must clear the applicant and the personal data fields in the data, in every
version and in every stored diff. It must use the personal data keys of all form versions of
the type. It must delete the magic links and the attachments.
