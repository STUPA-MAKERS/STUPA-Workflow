---
name: nextcloud-parity-ui
description: "User wants admin UIs modeled closely on Nextcloud's equivalents"
metadata: 
  node_type: memory
  type: feedback
---

The user repeatedly asks for admin UIs that look/work like their Nextcloud counterparts: the **user list as the Nextcloud users table**, and the **Form-Builder ~1:1 like Nextcloud Forms**.

**Why:** Nextcloud is the team's reference for "good, non-clunky" admin UX; "clunky" / "cluttered" / "null sinn" are the recurring complaints.

**How to apply:** When building/reworking an admin screen, look at the Nextcloud equivalent (user management table, Forms question editor) and match the layout/interaction model — table-based lists, per-row actions, drag-reorder, inline editors — rather than ad-hoc forms. See [[antragsplattform-backlog]].
