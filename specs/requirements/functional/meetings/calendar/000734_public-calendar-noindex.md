---
id: "000734"
title: The public calendar is not indexed
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - backend/app/modules/calendar/public_router.py
  - frontend/src/app/features/calendar/calendar.component.ts
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# The public calendar is not indexed

The public calendar page and the public ICS feed must send `noindex` (meta robots and
`X-Robots-Tag`).

Reason: The public pages of the platform are for persons who open them, not for search engines
(§F/public/public-pages/000173).

Test: A backend unit test fetches the public ICS feed and finds the header `X-Robots-Tag:
noindex`.
