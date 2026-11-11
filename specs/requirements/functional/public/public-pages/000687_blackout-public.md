---
id: "000687"
title: The public variants black out a marked segment
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
  - typst/
  - frontend/src/app/features/public-protocols
  - frontend/src/app/features/public-meeting
---

# The public variants black out a marked segment

The public PDF, the public protocol page and the guest view of a public meeting must show a
black bar in place of each marked segment. The server must remove the marked text before it
stores the public snapshot, before it sends the public Markdown to typst and before it sends
the guest view. The public search must not find the marked text. The bar must have the text
alternative "geschwärzt" for a screen reader.

Reason: A name must not leave the server in a public answer, not even in the HTML source or
the PDF text layer.

Test: A backend test checks that the public snapshot, the public typst input and the guest
view hold no marked text.
