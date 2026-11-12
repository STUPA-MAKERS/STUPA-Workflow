---
id: "000682"
title: The class view shows every database model and its relations
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "backend/tests/unit/scripts/test_build_uml.py:test_class_view_has_each_table_and_foreign_key"
  - "backend/tests/unit/scripts/test_build_uml.py:test_check_values_reads_an_in_list"
implementation:
  - scripts/build_uml.py
  - specs/uml/classes.json
scope:
  - specs/
  - scripts/
  - backend/app/modules
---

# The class view shows every database model and its relations

`classes.json` must hold one element for each SQLAlchemy model of `backend/app/modules`. Each
element must have its `module`, its `table`, and its `attributes`: one entry for each column,
with `name`, `type`, `nullable` and `primaryKey`. A column with a check constraint that lists
its values must also have these `values`.

The file must hold one edge for each foreign key. The edge must go from the model with the
foreign key to the model of the referenced table. It must have the `column`, the `onDelete`
action, and the `multiplicity`: `1` when the column is unique, otherwise `*`. The script must
read the models from the SQLAlchemy metadata, not from the source text.

Reason: The data model is spread over 30 modules. One view shows how the tables of different
modules hang together.

Test: A unit test builds the view and finds each table of the metadata and each foreign key.
