---
id: "000434"
title: Dev follows development, production follows tags
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - deploy/
---

# Dev follows development, production follows tags

`dev.workflow.reutlingen.university` deploys every merge into `development` and runs the
migrations. Production follows the newest release tag `vYYYY.MM.N`, not `main`.
