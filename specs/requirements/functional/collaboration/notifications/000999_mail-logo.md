---
id: "000999"
title: The head of a mail shows the logo of the branding
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

# The head of a mail shows the logo of the branding

The head of every mail must show the Wortmarke of the active branding. If the branding has no
Wortmarke, the head must show the Bildmarke and the platform name (000998) as text. If the
branding has no logo, the head must show only the platform name.

The mail must carry the logo as an inline PNG part of the mail. The mail must not load the logo
or any other resource from a server. The logo must have the platform name as its alternative
text. The mail must show the logo at a height of 40 px, and the PNG must be at most 120 px
high. A logo that the branding holds only as a URL counts as no logo. The plain-text part of a
mail has no logo.

Reason: A mail client blocks remote images and removes `data:` images, so only an inline part
shows without a click. A remote image also tells the server who opened the mail. Not every
mail client shows WebP or ICO, and every client shows PNG.

Test: Tests build a mail with a Wortmarke, with only a Bildmarke, with a URL logo and without a
logo. They read the head and the inline part and check that the HTML has no remote URL in an
`src`.
