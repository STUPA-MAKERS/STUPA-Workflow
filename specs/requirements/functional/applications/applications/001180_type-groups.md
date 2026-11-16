---
id: "001180"
title: Admins group the Antragsarten
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/admin/test_application_type_groups.py:test_group_crud_and_delete_keeps_the_types"
implementation:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin/forms
scope:
  - backend/app/modules/application_types
  - backend/app/modules/admin
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# Admins group the Antragsarten

An admin must be able to create, edit and delete groups of Antragsarten on the page "Anträge &
Formulare". A group must have a name in German, an optional name in English and an optional
Markdown text in German and English. Each Antragsart must belong to no group or to exactly one
group. The admin must set the group of an Antragsart on the same page. When a group is deleted,
its Antragsarten must stay and must have no group.

Reason: The step "Antragsart wählen" shows many types in one list. A group puts related types
together and gives them one explaining text, for example "Projektanträge" for VSM and QSM.

Test: The backend tests create, edit and delete a group and check that the delete keeps the
types. The page tests check the group dialog and the group choice of a type.
