---
id: "000053"
title: Only the owner tags a release
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - .
scope:
  - .
---

# Only the owner tags a release

Only the owner creates a release tag `vYYYY.MM.N` and a GitHub release. An agent must not tag,
not create a release and not offer to do it. `N` is a counter in the month, not the day.

Reason: Production follows the newest release tag.
