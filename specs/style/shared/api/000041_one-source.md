---
id: "000041"
title: Shared data has one source
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/
  - frontend/
  - mcp/
  - typst/
  - deploy/
---

# Shared data has one source

Data that two parts of the system read must exist in one file only. Both parts read that
file. Do not commit a generated copy. Example: the UI texts live only in
`frontend/src/app/core/i18n/catalog/{de,en}.json`, and the backend reads the same files
through a read-only mount.

Reason: A copy drifts from its source.
