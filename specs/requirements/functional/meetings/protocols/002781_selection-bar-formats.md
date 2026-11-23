---
id: "002781"
title: The format bar holds the inline formats
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - frontend/vendor/ui-kit/markdown-editor/src/markdown-editor.component.ts
scope:
  - frontend/vendor/ui-kit/markdown-editor
---

# The format bar holds the inline formats

The format bar (002780) must hold three buttons in this order: Fett, Kursiv and Schwärzung
(000685). A button must switch its format on the selection, the same way as the button of the
toolbar does. A button must show as pressed while the whole selection has its format. The
selection must stay after a press, so that the person can set a second format.

Reason: These three formats apply to a part of a line. Heading, list and quote apply to a whole
block, so they stay in the toolbar.

Test: A unit test of the editor presses each button on a selection and checks the Markdown and
the pressed state.
