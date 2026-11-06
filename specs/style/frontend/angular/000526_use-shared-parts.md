---
id: "000526"
title: A view uses the shared components
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
---

# A view uses the shared components

A view must build a part from the shared component or the shared style that exists for it:
a section heading, a list of facts, a row list, a sheet, a dialog, an empty state, a note,
a skeleton. A view may style its own part only for a reason, and a comment beside that style
must name the reason.

Reason: A copied style drifts from the shared one, and one change in the shared component then
misses the copies.

Test: A review of each UI change. A screenshot shows the part beside the same part on another
page.
