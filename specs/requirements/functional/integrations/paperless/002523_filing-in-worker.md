---
id: "002523"
title: Filing runs in the worker and never blocks an action
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
---

# Filing runs in the worker and never blocks an action

The platform must file a document in a job of the worker. The action that causes the filing
must end before the job runs and must not fail when Paperless fails. The job must try again
after a failure, at most 8 times.

Reason: An outage of Paperless must not stop the finalization of a protocol or a decision
(000176).

Test: A unit test finalizes a protocol while the client raises an error and expects the
protocol final.
