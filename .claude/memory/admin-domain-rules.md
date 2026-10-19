---
name: admin-domain-rules
description: "Domain rules the user set for the admin area: admin role holds all rights, vote delegation is per Gremium, every i18n value editable in EN too, memberships and roles come only from OIDC groups"
metadata:
  node_type: memory
  type: project
---

Rules the user set for the admin area. Apply them to every change.

- **The `admin` role always has ALL permissions and is not editable.** The backend enforces
  it: `Principal.has()` passes for any in-scope permission when the principal holds `admin`
  (`auth/principal.py`), so the stored rights of the role do not matter. The RBAC service
  refuses to delete `admin` and `member` (`admin/service/rbac.py`). The Roles page
  (`pages/admin/roles`) shows both as fixed roles, `admin` read-only with every right.
- **Vote delegation is a per-Gremium setting**, not a per-user or per-role one. The flag is
  `gremium.allow_vote_delegation` (`allowVoteDelegation`); see the `be-delegations` skill.
- **Every i18n value must be editable in EN too, not only in DE.** This covers branding texts,
  Gremium names, form labels, flow state and transition labels, role names. A new editor that
  binds only `['de']` is a bug.
- **Memberships and roles come from OIDC groups only.** Nobody sets a Gremium membership or a
  global role assignment by hand. An OIDC group links in THREE SEPARATE ways, all on
  `/admin/group-mappings`: group → global role (`group_mapping`, no Gremium scope), group →
  Gremium membership (`gremium_membership_mapping`), group → Gremium role
  (`gremium_role_mapping`, only for members). The user was explicit: global roles, Gremien and
  Gremium roles are unrelated and must never be combined in one mapping. The login sync
  writes `gremium_membership`. The only `role_assignment` rows are the bootstrap ones. Do not
  add a manual write path back.

Role *permissions* live on their own page, `/admin/roles`.
