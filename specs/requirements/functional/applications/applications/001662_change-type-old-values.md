---
id: "001662"
title: Values the new form does not have stay readable
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "backend/tests/integration/modules/applications/test_type_change.py:test_change_with_missing_fields_sends_back"
  - "backend/tests/unit/modules/applications/test_type_change_unit.py:test_dropped_lists_old_values_that_do_not_move"
implementation:
  - backend/app/modules/applications/service/type_change.py
  - backend/app/modules/applications/router.py
  - backend/app/modules/applications/service/edits.py
  - frontend/src/app/pages/applications/type-change-dialog
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# Values the new form does not have stay readable

A change of the Antragsart (001660) must not delete a value. A value whose field the new form
does not have must stay in the old data version. The version view (000375) must show the old
version with all of its values.

Reason: The reviewer must still be able to read what the applicant entered in the old form.

Test: A backend unit test reads the old data version after the change.
