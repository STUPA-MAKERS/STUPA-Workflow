---
id: "002742"
title: The team files an attachment of a ticket in Paperless
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_paperless_webhooks.py:test_the_action_needs_paperless_use"
  - "backend/tests/integration/modules/tickets/test_ticket_paperless_webhooks.py:test_the_worker_files_the_file_with_the_ticket_number"
implementation:
  - backend/app/modules/tickets/paperless.py
  - backend/app/modules/tickets/router.py
  - backend/app/modules/paperless_filing/files.py
  - frontend/src/app/pages/tickets/ticket-detail.component.ts
scope:
  - backend/app/modules/tickets
  - backend/app/modules/files
---

# The team files an attachment of a ticket in Paperless

A clean file of a ticket must have the action `In Paperless ablegen` for a person with the work
right in the Bereich and the permission `paperless.use`, while the Paperless connection is on.
The filing must run in the worker (002523) and must name the number of the ticket in the title
of the document. After the filing the file must show `In Paperless öffnen` (002525).

Reason: Documents such as invoices arrive by mail. A person decides which file is a document for
the archive, because most attachments are not.

Test: A unit test starts the action without `paperless.use` and expects 403.
