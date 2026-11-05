---
id: "000268"
title: A magic link is valid until an event ends it
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
---

# A magic link is valid until an event ends it

A magic link has no expiry unless `link_ttl_days` is set. The redeem of a newer link, the
archive and the anonymization end it. A new request must not end other links.

Reason: Anybody who knows the address can request a link. Else a request could lock out the
applicant.
