---
id: "003018"
title: The page Rollen & Rechte shows the name of a permission with its key
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "frontend/src/app/pages/admin/roles/roles.component.spec.ts:AdminRolesComponent"
implementation:
  - frontend/src/app/pages/admin/roles
scope:
  - frontend/src/app/pages/admin/roles
---

# The page Rollen & Rechte shows the name of a permission with its key

On the page "Rollen & Rechte" (`/admin/roles`) the label of the checkbox of a permission must be
its name in the UI language (003017). The key must show below the name, in a smaller, muted
monospace font. A screen reader must read the name as the label of the checkbox and the key as
its description.

A key without a name (a key that the server adds before the frontend has its name) must show
the key as the label, and no second line.

Reason: An admin chooses a right by what it allows, and the key stays visible because the
specs, the audit log and the API name the right by its key.

Test: A unit test of the roles page checks the name, the key line and the fallback of a key
without a name.
