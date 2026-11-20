---
id: "001692"
title: The chosen visibility shows before sending
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/shared/ui/chat/chat.component.ts
  - frontend/src/app/shared/ui/chat/chat.component.scss
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The chosen visibility shows before sending

While a person writes a comment, the comment field must show the chosen visibility as text
next to the send button. A public comment must also show a different frame than an internal
comment. The difference must not depend on color alone.

Reason: The person must see the visibility before the mail goes out, not after.

Test: A frontend unit test checks the text and the frame for both values.
