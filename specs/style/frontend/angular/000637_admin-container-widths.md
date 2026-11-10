---
id: "000637"
title: Container queries in Verwaltung use three named widths
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/pages/admin
---

# Container queries in Verwaltung use three named widths

A container query in a stylesheet of Verwaltung must use one of three widths from one shared
SCSS module: 34 rem (the fields of a form stack), 44 rem (the columns of a row stack) and
56 rem (a wide row with five or more columns stacks). A stylesheet must not write another
width. A layout that changes to a named width must stack at the next larger one, so that no
row overflows.

Reason: The pages use nine widths (30, 34, 36, 40, 44, 48, 51, 52 and 56.5 rem), so two
pages with the same layout change at different window sizes.

Test: A source test reads every stylesheet below `pages/admin` and fails on an `@container`
rule that does not come from the shared module.
