---
id: "001853"
title: The members message is a mail template
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "backend/tests/integration/modules/gremien/test_gremium_notify.py:test_manager_notifies_every_active_member"
implementation:
  - backend/app/modules/notifications/texts/committees.py
  - backend/app/modules/notifications/templates_catalogue.py
scope:
  - backend/app/modules/gremien_overview
  - backend/app/modules/notifications
---

# The members message is a mail template

The message must use the mail template `gremium_message`, which an admin edits on the page of
the mail templates (DE and EN). The placeholders must be `gremiumName`, `senderName`,
`subject` and `message`. The mail must link the Gremium page `/committees/{id}`. A member must
not be able to switch the mail off in the own notification settings.

Reason: The text of the frame follows the branding like every other mail. A message of the
Gremium is official, like the mails of an Umlaufverfahren.

Test: A backend test that the catalogue holds `gremium_message` and that a send ignores the
notification preferences.
