---
id: "000160"
title: Membership sync deletes rows without history
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/admin/membership_sync.py
  - backend/app/modules/auth/service.py
  - backend/app/modules/auth/session_renewal.py
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# Membership sync deletes rows without history

The membership sync must write `gremium_membership` from the cached OIDC groups of a principal
and the group mappings. It must delete a row that no mapping supports, and it must not write a
history row for it. The sync must run at each OIDC login, at each session renewal, after each
change of a group mapping, at an erasure and at an account merge.

Reason: The OIDC groups are the only source of a membership, so the IdP holds the history.
