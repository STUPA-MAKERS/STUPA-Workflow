---
id: "002728"
title: A mail shows as text only
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A mail shows as text only

The text of a message from a mail must come from the plain text part of the mail. For a mail
with only an HTML part the platform must convert the HTML to text. The platform must not show
the HTML of a mail and must not load an image or a different resource that a mail names.

Reason: The HTML of a mail comes from a stranger. It can carry scripts, tracking images and a
fake of the UI.

Test: A unit test imports an HTML mail with a script and a remote image and expects a message
without tags and no request.
