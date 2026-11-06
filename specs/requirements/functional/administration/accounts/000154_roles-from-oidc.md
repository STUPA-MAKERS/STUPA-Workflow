---
id: "000154"
title: Memberships and roles come from OIDC groups
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# Memberships and roles come from OIDC groups

Gremium memberships and roles must come only from OIDC groups. On `/admin/group-mappings`, a
group links in three separate ways: to a global role, to a Gremium membership or to a Gremium
role. One mapping must not combine them. The platform must not have a manual write path for a
membership or a role.
