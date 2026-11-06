---
id: "000341"
title: File access follows the access to the Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/files/service.py
  - backend/app/modules/files/router.py
scope:
  - backend/app/modules/files
  - backend/app/modules/media
  - backend/app/modules/applications
---

# File access follows the access to the Antrag

The read access to an attachment must follow the read access to its Antrag. An attachment of a
personal data field must be visible only to who can see personal data.
