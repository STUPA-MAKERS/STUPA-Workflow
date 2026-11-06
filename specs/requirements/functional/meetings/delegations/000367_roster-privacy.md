---
id: "000367"
title: Roster names are visible only to the Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/service.py
scope:
  - backend/app/modules/delegations
---

# Roster names are visible only to the Gremium

Only an admin, `admin.delegations`, `meeting.view_all`, members, pool members and
`session.manage` of the Gremium must see the roster and pool names.
