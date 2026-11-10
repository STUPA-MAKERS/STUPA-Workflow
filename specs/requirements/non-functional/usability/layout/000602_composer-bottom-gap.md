---
id: "000602"
title: The comment input has the same gap below as at its side
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/shared/ui/chat/chat.styles.spec.ts:chat_styles.overlays"
implementation:
  - frontend/src/app/shared/ui/chat/chat.component.scss
scope:
  - frontend/src/app/shared/ui/chat
---

# The comment input has the same gap below as at its side

On a wide screen, the comment input of a chat must end on the inner edge of its pane. The gap
below the input must be the same as the gap at its start side (32px on a to-do card).
An overlay of the chat (dialog, side sheet, file viewer) must not take a place in the column
of the chat.

Reason: An overlay in the column adds one more gap of the column (12px) below the input, so
the input looks too high in its pane.

Test: The style spec of the chat checks that the overlays are out of the column. Screenshot of
an open to-do card in "Aufgaben" on a desktop width: the gap below the input and the gap at
its left side are equal.
