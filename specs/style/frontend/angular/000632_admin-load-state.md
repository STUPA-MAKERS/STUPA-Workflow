---
id: "000632"
title: An admin page shows its load states through app-load-state
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
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

Reason: Twelve pages wire the skeleton and the error by hand, each in another order. Six
templates show a load error as a note in the page, which `NF/usability/controls/000576`
forbids.

Test: A source test reads every template below `pages/admin` and fails on `<app-load-error`
and on `<app-skeleton` outside a `#loading` template.
