---
id: "000951"
title: Only info.write edits the Info of a Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/gremien/test_gremium_info.py:test_only_info_write_saves"
implementation:
  - backend/app/modules/gremien/gremium_roles.py
  - backend/app/modules/gremien_overview/info.py
  - backend/app/modules/auth/oauth.py
  - backend/migrations/versions/9a69ebacd008_gremium_info.py
scope:
  - backend/app/modules/gremien
  - backend/app/modules/gremien_overview
  - frontend/src/app/features/gremien
---

# Only info.write edits the Info of a Gremium

Only a holder of the Gremium permission `info.write` in that Gremium must be able to change the
text and the links of the Info tab. The forced roles `vorstand` and `manager` must have
`info.write` by default. The role `member` must not have it by default. A global role must not
grant it (000267). The OAuth scope `committees:write` must cap it.

Reason: The managers of a Gremium own its standing information. A separate permission lets a
Gremium give the right to other roles, for example a Schriftführung.

Test: A backend test that a `manager` saves, a `member` gets 403 and an admin without a
membership gets 403.
