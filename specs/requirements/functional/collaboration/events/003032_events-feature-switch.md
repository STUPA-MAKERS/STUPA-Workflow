---
id: "003032"
title: Veranstaltungen have a feature switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/router.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# Veranstaltungen have a feature switch

Veranstaltungen must have a switch under /admin/features (`events`). The switch must be on until
an admin switches it off, as each feature is. While `events` is off, each route under
`/api/events` must answer 404 `feature_disabled`, and the platform must show no element of the
feature: the page, its entry in the navigation, the link kind, the picker in a Buchung, the
entries in the calendar, the hits of the search and the nodes of the graph. The stored Events
must stay.

Reason: A student government without Events must not see a page that it does not use, and one
press must lose no data (003013).

Test: A backend unit test finds each route under `/api/events` in the feature `events`. A
frontend unit test finds the switch on the page of the features.
