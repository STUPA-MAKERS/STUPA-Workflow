---
id: "000668"
title: The fiscal year is chosen with a chip
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/pages/budget
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The fiscal year is chosen with a chip

A page that shows the data of one fiscal year must let the person choose the year with a
filter chip ("HHJ 2026") that opens a picker. The cost centre page of Verwaltung must not use
a segmented control for the year.

Reason: The number of fiscal years grows each year. A chip keeps its width, a segmented
control gets one segment more each year.

Test: A unit test of the cost centre page of Verwaltung expects the year chip and no
segmented control.
