---
id: "000279"
title: OIDC endpoints come from discovery
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# OIDC endpoints come from discovery

The server reads the OIDC endpoints from the discovery document. The `issuer` must equal
`OIDC_ISSUER` exactly. An unreachable IdP answers 503.
