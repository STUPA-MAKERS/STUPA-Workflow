---
name: no-uuids-in-ui
description: Never show a raw UUID, principal id or sub in the UI. Resolve ids to names on the server through auth/identity.py
metadata:
  node_type: memory
  type: feedback
---

NEVER show a raw UUID, principal id or `sub` anywhere in the UI. Show something
human-readable: the display name, else the email, else a generic label.

**Why:** a UUID means nothing to a user. The platform is for student-government members.

**How to apply:** resolve ids to names on the SERVER, in the serializer. The frontend renders
what it gets. Every name lookup goes through `app/modules/auth/identity.py`:
`refs_by_sub(session, subs)` and `refs_by_id(session, ids)` return a `PrincipalRef` per known
principal in one query. `.name` is the display name, else the email; it is `None` for an
anonymized account. The lookup follows an account merge, so an old `sub` shows the name of the
account it was merged into. Example: `ApplicationService._author_refs` /
`_resolve_actors` (`applications/service/service_base.py`) for the timeline and the versions.

When a lookup finds no name, leave the field empty or use a generic label; never fall back to
the raw id. When you add any "by X", "owner" or "assigned to" field, resolve the id before you
return it. A UUID on screen means a serializer skipped the name resolution.
