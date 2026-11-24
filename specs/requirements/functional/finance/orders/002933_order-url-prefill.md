---
id: "002933"
title: The form fills the link from the preferred offer
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages/applications
---

# The form fills the link from the preferred offer

When a person picks exactly one position in the form of a Bestellung and the link is empty, the
form must set the link to the first `http://` or `https://` address in the text of the
preferred offer of this position. The form must not change a link that the person typed. With
no address in the offer the link must stay empty.

Reason: Applicants write the address of the shop into the offer. The prefill saves the copy by
hand, and the person can still change the link.

Test: A frontend unit test picks a position with an address in the preferred offer and reads
the link, then types a link, picks a different position and reads the typed link.
