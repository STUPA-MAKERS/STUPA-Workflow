---
id: "002723"
title: The worker fetches the mails each minute
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
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
