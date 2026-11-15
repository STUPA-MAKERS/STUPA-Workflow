---
id: "001000"
title: The button and the links of a mail use the accent colour
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

# The button and the links of a mail use the accent colour

The button and the links of every mail must use the accent colour of the active branding
(`accentColor`). Without an accent colour, they must use the built-in accent `#72a384` of the
design system. The mail must derive the link colour and the text on the button from the accent
colour so that each has a contrast of at least 4.5:1 to its background, in the light and in
the dark colours (001004).

Reason: The accent colour is the colour of the platform. An admin sets it freely, so a fixed
text colour on it does not keep WCAG 1.4.3.

Test: A test renders the mail for the built-in accent and for a light, a dark and a saturated
accent, and computes the contrast of the link and of the button text.
