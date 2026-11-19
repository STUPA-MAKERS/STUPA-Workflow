---
id: "000399"
title: The design has one accent and plain status text
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/vendor/ui-kit/src/styles/tokens.scss
  - frontend/vendor/ui-kit/src/lib/status-text/status-text.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The design has one accent and plain status text

The app must have one accent colour. A status must be coloured text, without a dot or a pill. A status in the head of a page is a
chip (001305), and the facts below the title of a detail are chips too (001306). A
tag is a feature, not a status. Input fields must not have a shadow. Only persons must have
avatars.
