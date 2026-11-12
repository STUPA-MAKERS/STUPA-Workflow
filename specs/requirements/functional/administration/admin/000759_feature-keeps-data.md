---
id: "000759"
title: A switch keeps the data of the feature
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules
---

# A switch keeps the data of the feature

A switch that goes off must not delete or change a record of the feature. A switch that goes on
again must show the records as they were. The privacy export, the privacy erasure, the account
merge, the retention and the backup must include the records of a feature that is off.

Reason: A switch is a setting and must be reversible without a loss. The duties of data
protection do not depend on what the UI shows.

Test: A backend unit test creates a card, switches `Boards` off and on and reads the same card. A
second test runs the privacy export with `Boards` off and finds the card in it.
