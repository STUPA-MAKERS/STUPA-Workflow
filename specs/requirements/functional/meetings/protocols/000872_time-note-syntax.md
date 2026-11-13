---
id: "000872"
title: A protocol text marks a time note
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "typst/tests/test_markdown.py:test_time_note_keeps_inline_markdown_and_the_blackout"
  - "typst/tests/test_integration.py:test_time_notes_print_centered_above_the_top"
  - "frontend/src/app/shared/markdown/markdown.util.spec.ts:markdownToSafeHtml"
implementation:
  - typst/typst_service/markdown.py
  - typst/template/protocol.typ
  - frontend/src/app/shared/markdown/markdown.util.ts
  - frontend/vendor/ui-kit/markdown-editor/src/time-note.extension.ts
scope:
  - typst/
  - backend/app/modules/protocol
  - frontend/src/app/shared/markdown
---

# A protocol text marks a time note

The Markdown of a protocol must mark a time note as one line `> [!anmerkung HH:MM] <text>`.
This must work in each Markdown text of a protocol. The protocol PDF must show the note in the
style of the TOP time (000871): grey, small and centered, as `HH:MM Uhr · <text>`. The text
may hold inline Markdown and the blackout marker (000685). The public PDF must black out the
marked text of a note the same way as other text.

Reason: The protocol records events with their time, for example "[XYZ] verlässt die
Sitzung". The blackout hides a name in public.

Test: Unit tests of the typst converter, of the backend redaction and of the frontend renderer
parse a note with a blackout marker.
