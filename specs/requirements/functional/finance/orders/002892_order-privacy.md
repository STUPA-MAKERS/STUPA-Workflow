---
id: "002892"
title: The buyer of a Bestellung follows the privacy rules
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/privacy
  - backend/app/modules/orders
  - backend/app/modules/applications
---

# The buyer of a Bestellung follows the privacy rules

The data export of a person must list the Bestellungen that name the person as the buyer. The
erasure of an account must clear the buyer of these Bestellungen. The merge of two accounts must
move the buyer to the account that stays. The anonymization of an Antrag must keep its
Bestellungen and must clear a typed buyer name in each of them.

Reason: The buyer is the only personal data of a Bestellung. The other fields are records of the
finances, like a booking, and must stay for the Kassenprüfung.

Test: A backend integration test exports, merges and erases an account that is the buyer of a
Bestellung, anonymizes an Antrag and reads its Bestellungen without the buyer name.
