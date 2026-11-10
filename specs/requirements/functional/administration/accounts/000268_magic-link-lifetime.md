---
id: "000268"
title: A magic link is valid until an event ends it
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/auth/service.py
  - backend/app/modules/applications/guest_settings.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
---

# A magic link is valid until an event ends it

A magic link (000630) has no expiry unless `link_ttl_days` is set. The redeem of a newer magic
link, the archive and the anonymization end it. A new request must not end other links.

Reason: Anybody who knows the address can request a link. Else a request could lock out the
applicant.
