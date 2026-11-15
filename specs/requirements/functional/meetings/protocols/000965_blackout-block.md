---
id: "000965"
title: Protocol text marks a block for blackout
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/shared/blackout.py
  - typst/typst_service/markdown.py
  - frontend/src/app/shared/markdown/markdown.util.ts
  - frontend/vendor/ui-kit/markdown-editor/src/blackout.extension.ts
scope:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
  - typst/
  - frontend/src/app/shared/markdown
  - frontend/src/app/features/meetings
  - frontend/vendor/ui-kit/markdown-editor
---

# Protocol text marks a block for blackout

The Markdown of a protocol must mark a block of lines for blackout. A line that holds only
`%%` opens the block, and the next line that holds only `%%` closes it. The lines between can
hold each kind of Markdown: paragraphs, lists, tables, images and embedded PDFs (000862). A
block must not hold a second block. A `%%Name%%` in a block is allowed and has no extra
effect. The block must work in each Markdown text of a protocol: the TOP texts and the free
protocol text. A block without its closing line is an open marker (000686).

Reason: A protocol often treats a whole statement or a document that must not appear in
public. A segment on one line (000685) cannot hold paragraphs or attachments. A `%%` on its own
line cannot collide with `%%Name%%` in a line of text.

Test: Unit tests of the backend redaction, of the typst converter and of the frontend renderer
parse a block with two paragraphs and an embedded PDF.
