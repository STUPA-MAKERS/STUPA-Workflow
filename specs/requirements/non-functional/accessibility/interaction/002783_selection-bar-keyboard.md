---
id: "002783"
title: The format bar works with the keyboard
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/vendor/ui-kit/markdown-editor/src/markdown-editor.selection-bar.spec.ts:MarkdownEditorSelectionBar"
implementation:
  - frontend/vendor/ui-kit/markdown-editor/src/markdown-editor.component.ts
scope:
  - frontend/vendor/ui-kit/markdown-editor
---

# The format bar works with the keyboard

The format bar (002780) must be a `role="toolbar"` with an accessible name. Each button must have
an accessible name and `aria-pressed`. Alt+F10 in the text must move the focus to the first
button of the bar while the bar shows. The arrow keys must move the focus between the buttons.
Esc in the bar must hide the bar and move the focus back to the text with the same selection.
Tab must not stop on the bar while the focus is in the text. The bar must use the colours of
the menus, so that each display mode (Mehr Kontrast, Sehr hoher Kontrast, Transparenz
reduzieren) applies to it.

Reason: WCAG 2.1.1 and 4.1.2. A person without a pointer must reach every format of the bar.
Alt+F10 is the key of the floating toolbar in common editors.

Test: A unit test of the editor presses Alt+F10, the arrow keys and Esc and checks the focus and
the selection.
