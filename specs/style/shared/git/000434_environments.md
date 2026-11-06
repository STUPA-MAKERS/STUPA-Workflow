---
id: "000434"
title: Dev follows development, production follows tags
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - deploy/
  - README.md
scope:
  - deploy/
  - README.md
---

# Dev follows development, production follows tags

`dev.workflow.reutlingen.university` must deploy every merge into `development` and must run
the migrations. Production must follow the newest release tag `vYYYY.MM.N`, not `main`.
