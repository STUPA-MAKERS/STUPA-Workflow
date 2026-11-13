---
id: "000865"
title: Each page of an Anlage has a watermark
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation: null
scope:
  - typst/
---

# Each page of an Anlage has a watermark

Each page of an Anlage (000864) must have the watermark
`Anlage <N> zum Protokoll <Sitzungstitel> vom <TT.MM.JJJJ>`. The watermark must be one
diagonal line across the page, grey and transparent, so that the page below stays readable.
The watermark must be an artifact for a screen reader (000524).

Reason: A page that a reader takes out of the protocol PDF must still show that it is an
Anlage, and to which protocol it belongs.

Test: Integration test of the typst service: the text of each Anlage page holds the watermark.
