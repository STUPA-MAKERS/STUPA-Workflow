---
id: "000762"
title: The admin page Funktionen holds the feature switches
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# The admin page Funktionen holds the feature switches

The admin area must have the page `Funktionen` at `/admin/features` in the group
`Erscheinungsbild` of the admin navigation. Only a person with the permission `admin.features`
must be able to open the page and to change a switch.

The page must show one row for each feature with the name of the feature and its switch, in the
order of the navigation. A change must become active with `Speichern`. The save of a switch that
goes off must ask for a confirmation that names the feature.

The save must write a new version of the site configuration and an audit entry. A revert of that
entry must set the switches back.

Reason: Each admin page has its own permission. To switch a feature off changes the platform for
every person, so the right must be separate from the right for logos and texts, and the change
must be traceable.

Test: A backend unit test saves the switches without `admin.features` and gets 403. A second test
saves a switch and finds the new configuration version and the audit entry.
