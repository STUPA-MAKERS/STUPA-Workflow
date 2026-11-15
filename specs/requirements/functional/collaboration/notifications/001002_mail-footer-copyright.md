---
id: "001002"
title: The footer of a mail shows the copyright line
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_the_copyright_line_is_the_last_line_of_the_footer"
implementation:
  - backend/app/modules/notifications/brand.py
  - backend/app/modules/notifications/layout.py
scope:
  - backend/app/modules/notifications
  - backend/app/modules/protocol
  - backend/app/modules/site_config
  - backend/worker/mail.py
---

# The footer of a mail shows the copyright line

The last line of the footer of every mail must be the copyright line of the active branding
(`copyright`) in the language of the mail. If the line has no entry in that language, the
footer must use the German entry. Without a copyright line, the mail has no such line. The
plain-text part of the mail does not carry the line.

Reason: The copyright line names the body that sends the mail.

Test: Tests render a mail with and without a copyright line and read the footer.
