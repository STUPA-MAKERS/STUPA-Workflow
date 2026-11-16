---
id: "001003"
title: The footer of a mail shows the legal links
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_the_footer_shows_the_legal_links_in_one_line"
implementation:
  - backend/app/modules/notifications/brand.py
  - backend/app/modules/notifications/layout.py
scope:
  - backend/app/modules/notifications
  - backend/app/modules/protocol
  - backend/app/modules/site_config
  - backend/worker/mail.py
---

# The footer of a mail shows the legal links

The footer of every mail must show each legal link of the active branding (`legalLinks`) in
one line, in the order of the branding page. A link must have its label in the language of
the mail, or its German label if that language has none. The footer must turn a path that
starts with `/` into a full URL of the platform. The footer must leave out a link without a
label or with a URL that is not http, https or such a path. The plain-text part of the mail
must list each link as `label: URL`.

Reason: A reader of a mail must reach the Impressum and the Datenschutzerklärung of the
sender without a login. A relative link does not work in a mail client.

Test: Tests render a mail with an absolute link, a path link, a link without a label and a
`mailto:` link, and read both parts of the mail.
