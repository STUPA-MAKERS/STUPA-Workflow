---
id: "001660"
title: A submitted Antrag can change its Antragsart
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "backend/tests/integration/modules/applications/test_type_change.py:test_change_with_missing_fields_sends_back"
  - "backend/tests/integration/modules/applications/test_type_change.py:test_change_without_missing_fields_keeps_state"
  - "backend/tests/integration/modules/applications/test_type_change.py:test_change_refusals"
  - "backend/tests/unit/modules/applications/test_type_change_unit.py:test_carry_takes_same_key_same_type_and_valid_value"
implementation:
  - backend/app/modules/applications/service/type_change.py
  - backend/app/modules/applications/router.py
  - frontend/src/app/pages/applications/type-change-dialog
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A submitted Antrag can change its Antragsart

A person with the permission `application.change_type` must be able to change the Antragsart
of an Antrag that is not in the initial state. The new Antragsart must have an active form. The
change must write a new data version with the active form of the new Antragsart. It must carry
over each value whose field key exists in the new form with the same field type. A migration must
give the permission to the roles `finanzreferent` and `haushaltsbeauftragte` when these roles
exist.

Reason: Prod data holds 3 Anträge in the wrong form. One of them was changed by hand in the database. Today the only other way is to deny the Antrag and ask for a new one.

Test: A backend integration test changes the Antragsart and checks the carried values and the new form version.
