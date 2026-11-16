---
id: "001183"
title: Admins set the order of the groups and of the Antragsarten
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/admin/test_application_type_groups.py:test_move_groups_and_types"
implementation:
  - backend/app/modules/application_types
  - backend/app/modules/admin
  - frontend/src/app/pages/admin/forms
scope:
  - backend/app/modules/application_types
  - backend/app/modules/admin
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# Admins set the order of the groups and of the Antragsarten

An admin must be able to move a group up and down, and to move an Antragsart up and down inside
its group, on the page "Anträge & Formulare". The step "Antragsart wählen" and the public list of
Antragstypen must use this order. The order of the Antragsarten without a group must be set the
same way. A new group and a new Antragsart must go to the end.

Reason: Before this rule the internal key set the order, so "Projektantrag: VSM" stood last. With
a manual order the most used types stand first.

Test: The backend tests move a group and a type and check the order of the public list. The page
tests check the move actions.
