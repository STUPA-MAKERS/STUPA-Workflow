---
id: "000565"
title: A phone toast is a tinted glass card
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.scss
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.html
scope:
  - frontend/vendor/ui-kit
---

# A phone toast is a tinted glass card

On a phone, a toast must be a card with the corner radius `--radius-xl`. Its surface must be
`--color-selected` at 75 % over a backdrop blur of 16px. An error toast must use
`--color-danger-subtle` in place of `--color-selected`. The card must not have a coloured
edge.

The card must start with a round tile of 40px that shows the icon of the variant. The
message must be centred between the tile and the end of the card.

Reason: The selection colour is the tint of the active item of the bottom bar, so the toast
looks like a part of the app.
