---
id: "000636"
title: A component stylesheet has no class without a use
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/
---

# A component stylesheet has no class without a use

Every class selector in the stylesheet of a component must have a use in the template or in
the TypeScript file of the same folder. A class that is built at run time must have a
comment beside its rule that names the place.

Reason: About 100 classes in the app have no use, 36 of them in Verwaltung. They are the
rest of layouts that the shared components replaced, and they read as if the page still
had a look of its own.

Test: A source test reads each `*.component.scss` below `frontend/src/app`, takes every
class with a block prefix (`block__element`) and fails when the templates and TypeScript
files of the folder do not hold the name.
