---
id: "000517"
title: A status message is announced
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A status message is announced

A toast, a save result, a load error and a result count must be in a live region. The live
region must not move the focus.

Reason: WCAG 4.1.3. A screen reader user does not see a toast.
