---
id: "002723"
title: The worker fetches the mails each minute
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_a_failed_commit_leaves_the_mail_for_the_next_run"
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_a_failure_of_one_postfach_does_not_stop_the_others"
implementation:
  - backend/worker/ticket_mail.py
  - backend/worker/main.py
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# The worker fetches the mails each minute

A job of the worker must read the new mails of the inbox of each Postfach that is on, once a
minute. The job must store the position in the inbox only after the commit of the tickets. A
failure of one Postfach must not stop the fetch of the others. After eight failed runs in
sequence the admin page must show the error of the Postfach.

Reason: A mail must not get lost when the mail server or the platform fails in the middle of a
run.

Test: A unit test lets the commit fail and expects the same mail in the next run.
