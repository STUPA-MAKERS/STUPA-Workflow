---
name: admin-domain-rules
description: "Domain rules the user set for the admin area: admin role holds all rights, vote delegation is per Gremium, every i18n value editable in EN too, memberships and roles come only from OIDC groups"
metadata:
  node_type: memory
  type: project
---

The rules are specs in `specs/` of the STUPA-Workflow repository. Read the spec, not this
file:

- `F/administration/accounts/000155` The admin role has every permission
- `F/meetings/delegations/000110` Vote delegation is a Gremium setting
- `F/applications/forms/000136` Every i18n text is editable in English too
- `F/administration/accounts/000154` Memberships and roles come from OIDC groups
- `F/administration/accounts/000266` Every user holds the member role
- `F/administration/accounts/000267` Gremium rights come only from the membership
