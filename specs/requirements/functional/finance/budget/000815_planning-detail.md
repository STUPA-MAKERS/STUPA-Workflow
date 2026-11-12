---
id: "000815"
title: The detail of Planung shows the plan or one line
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - frontend/src/app/pages/budget
---

# The detail of Planung shows the plan or one line

In the view Planung the detail of the top-level Kostenstelle must show the steps (000806),
the sums (000807) and the tables (000808). The detail of a different Kostenstelle must show
its Ansatz, the Ansatz and the Ist of the year before, the Erläuterung, the Vermerke and a
table of its child Kostenstellen. The head of the detail must follow 000670.

Reason: The detail pane uses the full width for the plan, and a line needs room for its
Erläuterung.
