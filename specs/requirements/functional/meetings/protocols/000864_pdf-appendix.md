---
id: "000864"
title: The protocol PDF appends each embedded PDF as an Anlage
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation: null
scope:
  - backend/app/modules/protocol
  - backend/app/modules/media
  - typst/
---

# The protocol PDF appends each embedded PDF as an Anlage

The protocol PDF must append each embedded PDF (000862) after the signatures as an Anlage.
The Anlagen must have the numbers 1, 2, 3 in the order of their first reference. A PDF that
the text references two times must be one Anlage. Each page of an Anlage must be one page of
the protocol PDF and must keep its size and orientation.

Reason: The mailing list and the archive get one file. That file must hold the full record of
the Sitzung.

Test: Integration test of the typst service: a protocol with two references to one PDF and one
reference to a second PDF gives two Anlagen with all their pages.
