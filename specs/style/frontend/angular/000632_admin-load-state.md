---
id: "000632"
title: An admin page shows its load states through app-load-state
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/pages/admin/admin-load-state.templates.spec.ts:AdminLoadState"
implementation:
  - frontend/src/app/shared/ui/load-state/load-state.component.ts
  - frontend/src/app/pages/admin/admin-load-state.templates.spec.ts
scope:
  - frontend/src/app/pages/admin
  - frontend/src/app/shared/ui/load-state
---

# An admin page shows its load states through app-load-state

A page or a section of Verwaltung that reads data before it shows it must use
`app-load-state` for the states loading, forbidden, error and ok. The skeleton of the page
goes into the `#loading` template. A template of Verwaltung must not place `app-load-error`
or a loading skeleton by itself. A data table is the exception: it shows the load through
its own `loading` input.

A list that keeps its rows or its empty state below the load error sets `keepContent`. A
template with a `#loading` template must not call a member `loading()`, because the
reference hides the member in the whole template.

Reason: One component gives every page the same order of the states and the retry of
`NF/usability/controls/000576`. A page that wires the skeleton and the error by hand can
leave out the error or the retry.

Test: A source test reads every template below `pages/admin`. It fails on `<app-load-error`,
on `<app-skeleton` outside a `#loading` template, and on a call `loading()` in a template
with a `#loading` template.
