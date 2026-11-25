---
id: "003073"
title: The board kind of a permission is called permission
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/todos
  - backend/migrations
---

# The board kind of a permission is called permission

The board kind that a global permission guards must be stored as `permission`, not `team`.
The data migration must rename the kind. The UI of these boards must not change.

Reason: The word team names the new element. Two meanings of one word cause wrong access rules.

Test: A migration test reads the board Plattform as kind `permission` after the upgrade.
