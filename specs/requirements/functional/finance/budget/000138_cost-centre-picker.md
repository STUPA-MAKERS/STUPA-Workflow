---
id: "000138"
title: The cost centre pickers are fixed
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# The cost centre pickers are fixed

Every cost centre picker must be the search list of `app-cost-centre-select`. The one exception
is the form field "Kostenstelle": it must use the tree picker with colour swatches.
