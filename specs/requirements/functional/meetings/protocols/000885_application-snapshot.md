---
id: "000885"
title: The Anlage holds the Antrag as the Sitzung treated it
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
scope:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
  - backend/app/modules/applications
  - typst
---

# The Anlage holds the Antrag as the Sitzung treated it

The Anlage of 000884 must show the version of the Antrag that was current when the vote of
the TOP opened. If the TOP has no vote, it must show the version that was current when the
TOP closed. If the TOP did not close, it must show the version that is current at the
finalize. A later edit of the Antrag must not change the Anlage.

Reason: The protocol must show the text that the Gremium voted on, not a later version. The
Haushaltsplan Anlage uses the same point in time.

Test: Integration test: an edit of the Antrag after the vote opened does not change the Anlage
at the finalize.
