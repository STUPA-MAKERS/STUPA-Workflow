---
id: "002902"
title: The delegation dialogs pin the search
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/features/meetings/delegation-dialog/delegation-dialog.component.html
  - frontend/src/app/features/meetings/delegation-dialog/delegation-dialog.component.scss
  - frontend/src/app/features/meetings/lead-substitute-dialog/lead-substitute-dialog.component.html
scope:
  - frontend/src/app/features/meetings
---

# The delegation dialogs pin the search

In "Vertretung einrichten" and "Vertretung eintragen" the search must stay at the top of the
dialog body. Only the list below the search must scroll, in its own box with the scroll fade. The
search must filter every group of the list. The dialog must keep one height while the search runs.

Reason: In a long list the search scrolled away, and the dialog jumped in height with each hit
count.

Test: A component test that finds the search outside the scroll box of the list.
