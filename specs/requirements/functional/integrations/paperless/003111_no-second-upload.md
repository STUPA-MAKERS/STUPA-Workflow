---
id: "003111"
title: An uploaded file is never uploaded again by a new try
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_a_failed_task_read_does_not_upload_again"
implementation:
  - backend/app/modules/paperless/filings.py
  - backend/app/modules/paperless_filing/runner.py
scope:
  - backend/app/modules/paperless
  - backend/app/modules/paperless_filing
---

# An uploaded file is never uploaded again by a new try

After Paperless accepted the upload of a file, a new try of the job must only read the consume
task again and must not upload the file again. This applies to each failure of the read, also
when Paperless refuses the read or takes longer than 1 hour. Only a consume task that Paperless
ends with an error, or the action `Erneut versuchen` of an admin on a failed job, may start a
new upload.

Reason: A failed read does not show that Paperless has no document. Each new upload can make
one more copy of the same file. 8 tries made up to 8 copies of one Antrag.

Test: An integration test lets the read of the consume task fail 8 times and expects one upload
and a failed job.
