---
id: "002818"
title: A host allowlist has one check
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/shared/ssrf.py
scope:
  - backend/app/shared/ssrf.py
  - backend/app/modules
---

# A host allowlist has one check

A check of a host against an allowlist from the deploy configuration must call the one function
`host_allowed` in `app/shared/ssrf.py`. A module must not compare a host with an allowlist by
itself. An empty allowlist must allow no host, and an entry must be able to name a host alone or a
host with its port.

Reason: The webhooks, Paperless and the ticket mail each had their own check, and three copies of
a security check drift apart.

Test: A unit test of each caller passes a host outside the list and expects a refusal. An
import-linter or grep check finds a second comparison with an allowlist setting.
