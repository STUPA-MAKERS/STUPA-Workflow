---
name: no-uuids-in-ui
description: never surface raw UUIDs/ids in the UI — always resolve to human-readable names
metadata: 
  node_type: memory
  type: feedback
---

NEVER show a raw UUID, principal id or `sub` anywhere in the UI. Always show something
human-readable: display name, then email, then a generic label. Reported case: the
application timeline (German label "Verlauf") showed `von e03ad7d7-…`, because the
backend serialized the actor as `principal.sub`.

**Why:** a UUID means nothing to a user. The platform is for student-government members.

**How to apply:** resolve ids → names SERVER-SIDE in the serializer. The frontend renders
what it gets. Backend helper: `ApplicationService._author_names(subs) ->
{sub: display_name|email|sub}` (applications/service.py) maps `principal.sub` to a name.
We changed `timeline()` (actor) and `versions()` (changedBy) to use it (2026-06-14). The
same class of bug hit meetings (protokollantId compared to sub) — see
[[meetings-redesign]] and the `isProtokollant` flag. When you add any "by X", "owner" or
"assigned to" field, resolve the id before you return it. If you see a UUID on screen, a
serializer skipped the name resolution.
