---
id: "001692"
title: The chosen visibility shows before sending
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/shared/ui/chat/chat.component.ts
  - frontend/src/app/shared/ui/chat/chat.component.scss
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The chosen visibility shows before sending

While a person writes a comment, the visibility switch above the comment field must show the
chosen visibility. The switch is a segment selector whose options carry the labels of 001691.
The chosen segment is the only sign of the visibility: the comment field looks the same for
both values, with no extra frame or outline, also in the accessibility views. The chosen
segment differs from the other one by more than color alone.

Reason: The person must see the visibility before the mail goes out, not after.

Test: A frontend unit test checks the chosen segment for both values and that the comment field
has no extra frame for either value.
