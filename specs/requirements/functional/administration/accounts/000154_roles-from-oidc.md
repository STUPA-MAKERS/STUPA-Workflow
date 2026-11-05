---
id: "000154"
title: Memberships and roles come from OIDC groups
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# Memberships and roles come from OIDC groups

Gremium memberships and roles come only from OIDC groups. A group links in three separate
ways on `/admin/group-mappings`: to a global role, to a Gremium membership, to a Gremium role.
Do not combine them in one mapping. Do not add a manual write path.
