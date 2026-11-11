---
id: "000685"
title: Protocol text marks a segment for blackout
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/protocol
  - typst/
  - frontend/src/app/shared/markdown
  - frontend/src/app/features/meetings
---

# Protocol text marks a segment for blackout

The Markdown of a protocol must mark a segment for blackout as `%%<text>%%`. A `\%%` is a
literal `%%` and starts no marker. The marker must work in each Markdown text of a protocol:
the TOP texts and the free protocol text. The marked text is plain text and must not hold
other Markdown. The main use is a name.

Reason: A protocol often names a person who must not appear in public. `%%` is short to type
and does not collide with the pipe of a table or with the `{{…}}` shortcodes.

Test: Unit tests of the backend redaction, of the typst converter and of the frontend renderer
parse the marker.
