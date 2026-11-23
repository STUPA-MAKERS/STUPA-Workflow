---
id: "002767"
title: The links to Paperless have their own switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# The links to Paperless have their own switch

The admin page `Paperless` must have the switch `Paperless-Dokumente verknüpfen`, as one more
part of 002512. While the switch is off, `Verknüpfen` must not offer the kind, and `Verknüpft`
and the graph must not show a link with a Paperless end. The stored links must stay and must
show again when the switch goes on.

Reason: Each part of the integration has its own switch (002512). To link and to insert are two
different things.

Test: An integration test links a document, switches the part off and reads no Paperless link.
It switches the part on and reads the link again.
