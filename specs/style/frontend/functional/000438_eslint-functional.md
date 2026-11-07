---
id: "000438"
title: eslint-plugin-functional warns on mutation
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/eslint.config.js
  - frontend/vendor/ui-kit/eslint.config.js
scope:
  - frontend/
  - frontend/vendor/ui-kit
---

# eslint-plugin-functional warns on mutation

The frontend and the ui-kit must run `eslint-plugin-functional`. Its rules must be warnings,
not errors.
