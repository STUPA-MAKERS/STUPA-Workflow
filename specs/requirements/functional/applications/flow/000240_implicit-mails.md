---
id: "000240"
title: Every state change sends the implicit mails
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/notifications
---

# Every state change sends the implicit mails

Every fired transition mails the applicant and the people who can act in the new state. An
explicit applicant `notify` in the flow replaces the implicit applicant mail.
