---
id: "001004"
title: A mail has light and dark colours
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation: null
scope:
  - backend/app/modules/notifications
  - backend/app/modules/protocol
  - backend/app/modules/site_config
  - backend/worker/mail.py
---

# A mail has light and dark colours

The frame of every mail must have a light and a dark set of colours. The mail must use the dark
set when the mail client asks for it with `prefers-color-scheme: dark`, and the light set in
every other case. In each set, the text, the links and the button text must have a contrast of
at least 4.5:1 to their background. In the dark set, the head must show the logo of 000999 on a light
plate.

Reason: A mail client in dark mode inverts a mail that has only light colours, and the result
has no checked contrast. The branding has one logo, and a logo for a light page can
be unreadable on a dark one.

Test: A test reads both colour sets from the rendered mail and computes the contrast of each
text colour on its background.
