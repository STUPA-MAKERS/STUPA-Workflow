---
id: "000678"
title: A lost live connection shows as a toast
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/features/voting/vote-cast.component.spec.ts:VoteCastComponent"
implementation:
  - frontend/src/app/features/voting/vote-cast.component.ts
  - frontend/src/app/features/voting/vote-cast.component.html
  - frontend/vendor/ui-kit/src/lib/toast
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A lost live connection shows as a toast

When the live connection of a view is lost, the view must show the toast "Verbindung verloren
— verbinde neu …". The toast must stay while the connection is lost. It must close by itself
when the connection is back. The view must not show the text as a line in the page. On the phone
the toast must show as the bar at the top of the frame, so that it does not cover the back
arrow of the detail. While
the bar "Server nicht erreichbar" shows (000578), the toast must not show.

Reason: The vote detail shows the text as a small line above the title, where it moves the
content and is easy to miss. A person who votes must see that the view is not live.

Test: A unit test of the vote view ends the connection and expects one toast that stays
after the toast time, then restores the connection and expects no toast.
