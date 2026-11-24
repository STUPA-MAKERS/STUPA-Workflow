---
id: "002718"
title: The new assignee gets a mail
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_no_assigned_mail_for_the_own_take_over_or_a_stale_event"
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_an_assignment_by_another_person_mails_the_new_assignee"
implementation:
  - backend/app/modules/tickets/mails.py
  - backend/app/modules/tickets/router.py
  - backend/app/modules/notifications/texts/tickets.py
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# The new assignee gets a mail

When a person assigns a ticket to a different person, the new assignee must get a mail with the
number, the title and a link. A person who takes a ticket must get no mail.

Reason: In a team with many tickets the list does not show a person that a ticket is new for
that person.

Test: A unit test assigns a ticket to the own account and expects no mail.
