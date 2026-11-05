---
id: "000376"
title: An anonymization removes every copy of personal data
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/applications
  - backend/app/modules/privacy
---

# An anonymization removes every copy of personal data

An anonymization clears the applicant, the personal data fields in the data, in every version
and in every stored diff. It uses the personal data keys of all form versions of the type. It
deletes the magic links and the attachments.
