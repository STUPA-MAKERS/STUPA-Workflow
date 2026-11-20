---
id: "001692"
title: The chosen visibility shows before sending
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
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
A public comment must also show a different frame than an internal comment: the field of a
public draft has a solid outline, the field of an internal draft has none. The difference must
not depend on color alone.

Reason: The person must see the visibility before the mail goes out, not after.

Test: A frontend unit test checks the chosen segment and the frame for both values.
