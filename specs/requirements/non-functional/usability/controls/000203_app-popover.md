---
id: "000203"
title: Every dropdown uses the app popover
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/src/app/
  - ui-kit
---

# Every dropdown uses the app popover

Every dropdown, filter chip and select uses `app-filter-select` or the app popover, as a
popover on the desktop and a sheet on the phone. Do not use a native `<select>`.
