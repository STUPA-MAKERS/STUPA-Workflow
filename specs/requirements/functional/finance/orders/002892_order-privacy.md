---
id: "002892"
title: The privacy functions cover the buyer of a Bestellung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/privacy
  - backend/app/modules/budget
---

# The privacy functions cover the buyer of a Bestellung

The data export of a person must list the Bestellungen that name the person as the buyer. The
erasure of an account must clear `buyerId` and must set `buyerName` to empty for these
Bestellungen. The merge of two accounts must move `buyerId` to the account that stays.

Reason: The buyer is personal data. The other fields of a Bestellung are records of the finances
and stay.

Test: A backend integration test exports, merges and erases an account that is the buyer of a
Bestellung.
