---
id: "000455"
title: A long session is checked at the IdP again
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth
---

# A long session is checked at the IdP again

A principal session must run the refresh grant every `session_revalidate_hours`. A refused
refresh must end the session. An unreachable IdP must get `session_revalidate_grace_hours`,
then the session must end. No session must live longer than 400 days.

Reason: A removed group must lose its rights before the session ends.
