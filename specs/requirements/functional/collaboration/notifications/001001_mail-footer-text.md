---
id: "001001"
title: The footer of a mail shows the E-Mail-Fußzeile
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_the_footer_shows_the_footer_text_in_the_language_of_the_mail"
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_the_plain_text_ends_with_the_footer_text"
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_a_mail_without_a_footer_text_has_no_such_line"
implementation:
  - backend/app/modules/notifications/brand.py
  - backend/app/modules/notifications/layout.py
  - backend/app/modules/notifications/compose.py
scope:
  - backend/app/modules/notifications
  - backend/app/modules/protocol
  - backend/app/modules/site_config
  - backend/worker/mail.py
---

# The footer of a mail shows the E-Mail-Fußzeile

The footer of every mail must show the text "E-Mail-Fußzeile" of the active branding
(`freetexts.emailFooter`) in the language of the mail. If the text has no entry in that
language, the footer must use the German entry. The footer must keep the line breaks and show
each URL of the text as a link. The plain-text part of the mail must end with the same text.
Without a text, the mail has no such line.

The footer must not show HTML of the text as HTML.

Reason: The branding page offers the field, so the admin expects it in the mails. An escaped
text cannot bring script or markup into a mail.

Test: Tests render a mail with a footer text in two languages, with markup in it and without
one, and read both parts of the mail.
