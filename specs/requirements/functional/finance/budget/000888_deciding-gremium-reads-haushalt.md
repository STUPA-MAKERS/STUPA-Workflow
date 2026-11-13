---
id: "000888"
title: A Gremium that decides a plan reads the Haushalt
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/applications/test_committee_read_scope.py:test_a_gremium_that_decides_the_plan_reads_the_haushalt"
implementation:
  - backend/app/modules/budget/access.py
  - backend/app/modules/budget/tree/view.py
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/applications/access.py
scope:
  - backend/app/modules/budget
  - backend/app/modules/applications
  - backend/app/modules/search
  - backend/app/modules/account
---

# A Gremium that decides a plan reads the Haushalt

A member of a Gremium that decides the plan of a Haushalt in a step (000826) must read
this Haushalt like a member of its view Gremium (000259): the Kostenstellen with their
amounts, the Haushaltsplan with every version and its export, and the Anträge of its
Kostenstellen. A substitute of the pool of the Gremium reads like a member. The rule
gives no right to write.

The rule holds while the Haushalt has the plan switch on and its steps name the Gremium.

Reason: A Gremium can decide on a plan only when its members can read the plan and the
Haushalt that it plans.

Test: Integration test: a Gremium is in a step of a Haushalt without a view Gremium. With
the plan switch off, a member reads neither the Kostenstellen nor an Antrag of the
Haushalt. With the plan switch on, the member reads both.
