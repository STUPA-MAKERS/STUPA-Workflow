---
name: no-uuids-in-ui
description: never surface raw UUIDs/ids in the UI — always resolve to human-readable names
metadata: 
  node_type: memory
  type: feedback
---

NEVER show a raw UUID / principal id / `sub` anywhere in the UI — always human-readable
(display name, then email, then a generic label). Reported case: application timeline
("Verlauf") showed `von e03ad7d7-…` because the backend serialized the actor as
`principal.sub`.

**Why:** UUIDs are meaningless to users; the platform is for student-government members.

**How to apply:** resolve ids → names SERVER-SIDE in the serializer (the FE just renders
what it's given). Backend helper: `ApplicationService._author_names(subs) ->
{sub: display_name|email|sub}` (applications/service.py) maps `principal.sub` to a name.
Fixed `timeline()` (actor) and `versions()` (changedBy) to use it (2026-06-14). The same
class of bug hit meetings (protokollantId compared to sub) — see [[meetings-redesign]] /
the `isProtokollant` flag. When adding any "by X" / "owner" / "assigned to" field, resolve
the id before returning it. If you see a UUID on screen, it's a serializer that skipped
name resolution.
