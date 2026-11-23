---
id: "002780"
title: A text selection shows a format bar
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - frontend/vendor/ui-kit/markdown-editor/src/markdown-editor.component.ts
scope:
  - frontend/vendor/ui-kit/markdown-editor
  - frontend/src/app/features/meetings
---

# A text selection shows a format bar

When a person selects text in an editable Markdown text of a protocol (000862), the editor must
show a small format bar at the selection. The bar must show only while the selection holds text.
The bar must hide when the selection becomes empty, when the focus leaves the text and the bar,
when the person types, and when the person presses Esc. A read-only text must not show the bar.
The format bar must not replace the toolbar of the TOP.

Reason: A person formats a selected word without a move of the pointer to the toolbar, and on a
phone without the dock "Aa".

Test: A unit test of the editor selects text, collapses the selection and switches the editor to
read-only, and checks the bar each time.
