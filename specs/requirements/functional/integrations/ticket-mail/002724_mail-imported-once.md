---
id: "002724"
title: A mail is imported one time
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_the_same_mail_is_imported_one_time"
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_a_mail_without_a_message_id_is_imported_one_time"
  - "backend/tests/unit/modules/tickets/test_ticket_mail_parse.py:test_a_mail_without_a_message_id_gets_the_hash_of_its_source"
implementation:
  - backend/app/modules/tickets/mail_import.py
  - backend/app/modules/tickets/mail_parse.py
  - backend/app/modules/tickets/models.py
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# A mail is imported one time

The platform must import a mail of a Postfach only once. The `Message-ID` together with the
Postfach is the identity of a mail. A mail without a `Message-ID` must get the SHA-256 of its
source as identity.

Reason: A second run after a failure, and a mail that a person moves back to the inbox, must not
make a second ticket.

Test: A unit test fetches the same mail two times and expects one ticket.
