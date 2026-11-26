---
id: "003076"
title: Every team member sees the tab Teams
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-26
implementation:
  - backend/app/modules/account/router.py
  - frontend/src/app/core/auth/auth.service.ts
  - frontend/src/app/core/auth/auth.guard.ts
  - frontend/src/app/layout/nav.service.ts
  - frontend/src/app/app.routes.ts
scope:
  - frontend/src/app/layout/nav.service.ts
  - frontend/src/app/app.routes.ts
  - backend/app/modules/account
---

# Every team member sees the tab Teams

The navigation must show the tab Teams, and the route `/teams` must open, for a person who is a
member of at least one team (an inherent team or a free team), who has the permission
`team.create`, or who has the permission `gremium.view_all`. `GET /api/auth/me` must say in the
field `in_any_team` whether the person is a member of at least one team.

Reason: A person who is only in a free team must reach that team, and a person who may create a
team must reach the button "Team anlegen".

Test: A frontend unit test shows the tab for a member of a free team only and for `team.create`
only, and hides it for a person with neither. A backend test reads `in_any_team` for a member of a
free team.
