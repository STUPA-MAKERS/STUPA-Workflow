---
id: "000650"
title: Antrag stellen stands in the tab line of the desktop start page
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/src/app/pages/dashboard
---

# Antrag stellen stands in the tab line of the desktop start page

On a desktop width, the start page must show "Antrag stellen" as a filled button at the end of
the tab line of the work list, after the link "Alle". The button must use the look of the
button "Live beitreten" of the sheet "Heute". The desktop start page must not show a floating
button. The tab line must keep its height. On the phone, "Antrag stellen" stays the floating
button (000198).

Reason: The floating button stood at the foot of the list column. There it was in the middle
of the window and covered the last rows of the table. The tab line has free room, and a button
there covers nothing.

Test: A frontend unit test finds the link to `/apply` in the tab line and no floating button
on a desktop width, and the floating button on a phone width. Screenshots of both tabs in the
light theme, the dark theme and with very high contrast.
