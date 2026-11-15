---
id: "000998"
title: A mail names the platform by its branding name
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

# A mail names the platform by its branding name

Every mail must name the platform by the app name of the active branding (`appName`). This
covers the head of the mail, the footer, the display name of the sender and the built-in
texts. A mail template can use the name as `{{ platformName }}`. If the app name is empty,
the mail must use the sender name of the server settings (`MAIL_FROM_NAME`).

A built-in text must not contain a fixed platform name.

Reason: The admin names the platform on the branding page. A mail with a different name looks
like a mail from a different sender.

Test: Tests render a mail with and without an app name and read the head, the footer, the
sender and the built-in subject of the access link.
