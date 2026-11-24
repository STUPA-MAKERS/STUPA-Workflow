---
id: "002868"
title: A sum above the approved amount warns and does not block
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/orders/rules.py
  - frontend/src/app/pages/applications/orders/orders-section.component.ts
scope:
  - backend/app/modules/orders
  - frontend/src/app/pages/applications
---

# A sum above the approved amount warns and does not block

The sum of the Bestellungen of an Antrag is the sum of the real price, else the planned price,
of each Bestellung that is not "Storniert". When the sum is above the approved amount, the
section "Bestellungen" must show a warning with the difference. The server must not refuse a
Bestellung because of the sum.

Reason: A price often differs by the shipping or by some cents. A block would stop the entry of
a purchase that is already made. The available amount of a Kostenstelle can be negative too
(F/finance/budget/000248).

Test: A backend unit test of the sum leaves out a cancelled Bestellung. A frontend unit test
shows the warning above the approved amount and no warning at the approved amount.
