---
id: "000134"
title: Offer counts have limits
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/forms
  - frontend/src/app/pages/admin
scope:
  - backend/app/modules/forms
  - frontend/src/app/pages/admin
---

# Offer counts have limits

A positions field must need at least `minPositions` positions (default 1) and `minOffers`
offers per position (default 3). It must allow at most 200 positions and 50 offers per
position. A position with `noOffers: true` must have a `noOffersReason` and exactly one offer.
