---
id: "000390"
title: The typst version is pinned in two places
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - typst/
  - .github/workflows
---

# The typst version is pinned in two places

The typst version is pinned and checksum-checked in the `Dockerfile` and in the CI `typst` job.
Both must name the same version.
