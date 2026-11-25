---
id: "003110"
title: The PDF of an Antrag is filed when the Antrag reaches an end state
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_an_antrag_is_filed_only_in_an_end_state"
implementation:
  - backend/app/modules/paperless_filing/sources.py
  - backend/app/modules/paperless_filing/files.py
scope:
  - backend/app/
  - frontend/src/app/
---

# The PDF of an Antrag is filed when the Antrag reaches an end state

When an Antrag enters a state with the flag `Endzustand` (`isTerminal`) in the flow config, the
platform must file the PDF of the Antrag in Paperless. A change into a state without this flag
must not file a document, also when the state is approved or denied. The PDF must be the PDF of
the export (000882) at that moment. The download of the export must not file a document.

When the Antrag leaves the end state and enters an end state again, the platform must file the
new PDF as a new document (002521).

Reason: An Antrag changes until its end. Only the document of its end state belongs in the
archive. The flow config, not the code, says which state is an end state.

Test: An integration test moves an Antrag through an approved state without the flag into an end
state and expects one job, at the end state. A second test downloads the export and expects no
job.
