---
id: "000203"
title: Every dropdown uses the app popover
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Every dropdown uses the app popover

Every dropdown, filter chip and select must use `app-filter-select` or the app popover, as a
popover on the desktop and a sheet on the phone. A view must not use a native `<select>`.
