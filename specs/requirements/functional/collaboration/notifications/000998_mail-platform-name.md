---
id: "000998"
title: A mail names the platform by its branding name
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_the_mail_names_the_platform_by_the_app_name"
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_an_empty_app_name_gives_the_sender_name_of_the_server"
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_no_footer_reason_holds_a_fixed_platform_name"
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_the_access_link_subject_names_the_platform"
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_a_db_template_can_use_the_platform_name"
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_the_sender_name_is_quoted_and_encoded"
  - "backend/tests/unit/modules/notifications/test_mail_branding.py:test_the_brand_comes_from_the_active_site_config"
implementation:
  - backend/app/modules/notifications/brand.py
  - backend/app/modules/notifications/compose.py
  - backend/app/modules/notifications/layout.py
  - backend/app/modules/notifications/mail.py
  - backend/app/modules/notifications/service.py
  - backend/app/modules/notifications/texts/captured.py
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
