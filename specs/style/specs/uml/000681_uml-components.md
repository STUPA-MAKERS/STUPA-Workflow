---
id: "000681"
title: The component view shows the backend modules, their layers and their imports
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "backend/tests/unit/scripts/test_build_uml.py:test_component_view_has_the_layer_of_each_module"
implementation:
  - scripts/build_uml.py
  - specs/uml/components.json
scope:
  - specs/
  - scripts/
  - backend/pyproject.toml
---

# The component view shows the backend modules, their layers and their imports

`components.json` must hold one element for each package in `backend/app/modules` and one
element `shared` for the shared code (000644). Each module element must have its `layer`, the
number from 1 (top) to 5 (bottom) of the import contract in `backend/pyproject.toml` (000643).
The element `shared` must have the layer 6.

The file must hold one edge for each pair of modules where the first module imports the second
one, also through an import inside a function. The edge must have `count`, the number of import
lines. The script must read the imports with the same import graph that `lint-imports` uses.

Reason: The layers of 000643 are a list of names. The view shows which modules use which other
modules, and how strongly.

Test: A unit test builds the view and finds the layer of each module of the import contract.
