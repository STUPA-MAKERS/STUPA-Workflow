---
id: "002610"
title: A settings screen of Verwaltung shows no change date
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/admin/login-settings/login-settings.component.spec.ts:shows no change date, also after a change"
implementation:
  - frontend/src/app/pages/admin/login-settings/login-settings.component.ts
scope:
  - frontend/src/app/pages/admin
---

# A settings screen of Verwaltung shows no change date

A settings screen of Verwaltung must not show the date or the author of the last change of its
settings. This includes the screen "Anmeldung".

Reason: No other settings screen shows a change date, so one line of this type is
inconsistent. The audit log records each change with its time and its author.

Test: A unit test of "Anmeldung" expects no "Zuletzt geändert" with a stored change date.
