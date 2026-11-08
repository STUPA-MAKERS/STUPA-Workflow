---
id: "000509"
title: Sticky bars do not hide the focus
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/vendor/ui-kit/src/lib/focus/focus-reveal.spec.ts:watchFocusReveal"
implementation:
  - frontend/vendor/ui-kit/src/lib/focus/focus-reveal.ts
  - frontend/vendor/ui-kit/shell/src/shell/shell.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Sticky bars do not hide the focus

The header, the bottom bar, a FAB and a sticky head must not hide the focused control. The
scroll padding of a scroll area must be equal to the height of its sticky bars.

Reason: WCAG 2.4.11.
