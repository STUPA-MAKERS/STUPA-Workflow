---
id: "001652"
title: A forced change without a reason counts as Ohne Grund
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/flow
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A forced change without a reason counts as Ohne Grund

A forced status change that was made before 001650 has no reason key. The page of 001651 must
count it as `Ohne Grund` (`No reason`).

Reason: The report must also count the old forced changes, because they show the most frequent paths today.

Test: A backend unit test counts a forced change without a reason key.
