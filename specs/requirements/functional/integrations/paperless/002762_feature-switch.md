---
id: "002762"
title: Paperless has a feature switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# Paperless has a feature switch

Paperless must have a switch under /admin/features (`paperless`). The switch must be on until
an admin switches it off, as each feature is. While it is off, the platform
must not call Paperless: the worker must file nothing, the routes under `/api/paperless` and
`/api/admin/paperless` and the copy route of the insert must answer 404 `feature_disabled`, and
the platform must show no element of the integration (the admin page `Paperless`, the entry `In
Paperless öffnen`, the insert with `::`, the link kind of 002763). The stored connection, the
switches of the parts (002512) and the filed documents must stay. When the switch goes on
again, each part must return to the state of its own switch.

Reason: An admin stops the whole integration with one press, for example during a move of the
archive, and loses no setting.

Test: An integration test switches `paperless` off, gets `feature_disabled` from the search and
runs the worker without a call to Paperless. It switches the feature on and reads the stored
switches.
