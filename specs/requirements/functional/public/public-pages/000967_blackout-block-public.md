---
id: "000967"
title: The public variants show a blackout block as one bar
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "typst/tests/test_markdown.py:test_empty_blackout_block_is_one_full_bar"
implementation:
  - backend/app/shared/blackout.py
  - backend/app/modules/protocol/service.py
  - backend/app/modules/livevote/guests.py
  - typst/template/protocol.typ
  - frontend/src/app/shared/markdown
scope:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
  - typst/
  - frontend/src/app/features/public-protocols
  - frontend/src/app/features/public-meeting
---

# The public variants show a blackout block as one bar

The public PDF, the public protocol page and the guest view of a public meeting must show one
black bar in place of each blackout block (000965). The bar must have the full text width and
the height of one line, whatever the length of the block. It must have the colour of the bar of
a segment (000688). The bar must have the text
alternative "Abschnitt geschwärzt" for a screen reader. The server must remove the content of
the block before it stores the public snapshot, before it sends the public Markdown to typst
and before it sends the guest view, as for a segment (000687). A vote snippet in a block is
removed with the block, so the public variant shows the vote as its own box below the TOP
text, as for a vote that is not in the text.

Reason: The bar shows that the text has a gap there, but not how long the gap is. The result
of a vote is public, a blackout must not hide it.

Test: A backend test checks that the public snapshot, the public typst input and the guest
view hold no text of the block.
