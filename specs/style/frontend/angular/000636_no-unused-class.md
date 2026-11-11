---
id: "000636"
title: A component stylesheet has no class without a use
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/unused-class.styles.spec.ts:ComponentStylesheets"
implementation:
  - frontend/src/app/unused-class.styles.spec.ts
scope:
  - frontend/src/app/
---

# A component stylesheet has no class without a use

Every class with a block prefix (`block__element`) in the stylesheet of a component must have
a use in a template or in a TypeScript file of the same folder. A modifier
(`block__element--state`) also has a use when the folder builds its name from
`block__element--`. A class of another component, which the stylesheet styles from outside,
must have a use in that component.

Reason: A class without a use is the rest of a layout that a shared component replaced. It
reads as if the page still had a look of its own, and it hides which rules the page needs.

Test: `frontend/src/app/unused-class.styles.spec.ts` reads each `*.component.scss` below
`frontend/src/app` and fails on a class that neither the folder nor, for a class of another
component, the app or the ui-kit holds.
