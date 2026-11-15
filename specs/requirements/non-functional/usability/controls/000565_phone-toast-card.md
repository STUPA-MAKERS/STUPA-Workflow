---
id: "000565"
title: A toast is a tinted glass card
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.scss
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.html
  - frontend/src/app/pages/applications/applications-list.component.ts
  - frontend/src/app/pages/invoices/invoices.component.ts
scope:
  - frontend/vendor/ui-kit
  - frontend/src/app/
---

# A toast is a tinted glass card

A toast must be a card with the corner radius `--radius-xl`, on a phone and on a wider
screen. Its surface must be `--color-selected` at 75 % over a backdrop blur of 16px. An
error toast must use `--color-danger-subtle` in place of `--color-selected`. The card must
not have a coloured edge.

The card must start with a round tile of 40px that shows the icon of the variant. The
message must be centred between the tile and the end of the card.

The action of a toast (for example "Rückgängig") must be a round icon button of 40px at the
end of the card. Its label must be the accessible name and the tooltip of the button. A
phone toast without an action must keep an empty space of 40px at the end, so that the
message stays centred. The close button of a wide screen (000564) must be a round tonal icon
button of 40px, like the action button.

Reason: The selection colour is the tint of the active item of the bottom bar, so the toast
looks like a part of the app. A text button made the card uneven and took room from the
message. One toast must look the same on every width.
