---
id: "000154"
title: Memberships and roles come from OIDC groups
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/admin/oidc_mappings.py
  - backend/app/modules/gremien/membership_sync.py
  - frontend/src/app/pages/admin/group-mappings/group-mappings.component.ts
  - backend/app/modules/auth/rbac.py
  - backend/app/modules/auth/bootstrap.py
  - mcp/antragsplattform_mcp/tools
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
  - backend/app/deps.py
  - mcp/
---

# Memberships and roles come from OIDC groups

Gremium memberships and roles must come only from OIDC groups. On `/admin/group-mappings`, a
group links in three separate ways: to a global role, to a Gremium membership or to a Gremium
role. One mapping must not combine them. The platform must not have a manual write path for a
membership or a role, and no MCP tool must write one. Every principal must hold the role
`member`. Every other global role must come only from a group mapping and from the bootstrap.
