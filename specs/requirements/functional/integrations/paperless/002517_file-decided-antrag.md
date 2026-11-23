---
id: "002517"
title: The PDF of an Antrag is filed at each decision
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# The PDF of an Antrag is filed at each decision

When an Antrag enters a state that is approved or denied, the platform must file the PDF of
the Antrag in Paperless. The PDF must be the PDF of the export (000882) at that moment. The
download of the export must not file a document.

Reason: The export renders at each download, also while the Antrag changes. The archive must
hold the Antrag as it was at its decision.

Test: A unit test moves an Antrag into an approved state and expects one job. A second unit
test downloads the export and expects no job.
