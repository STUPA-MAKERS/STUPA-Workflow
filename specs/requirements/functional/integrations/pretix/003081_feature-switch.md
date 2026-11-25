---
id: "003081"
title: Pretix has a feature switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# Pretix has a feature switch

Pretix must have a switch under /admin/features (`pretix`). The switch must be on until an
admin switches it off, as each feature is. While it is off, the platform must not call pretix,
each route under `/api/pretix` and `/api/admin/pretix` must answer 404 `feature_disabled`, and
the platform must show no element of the integration. The connection, the switches of the parts
(003082) and the links of the Events must stay. While the feature `events` (003032) is off, the
platform must show no element of the integration either.

Reason: An admin stops the whole integration with one press and loses no setting. The
integration exists only for the Events.

Test: A backend unit test finds each route under `/api/pretix` in the feature `pretix`, switches
it off and gets `feature_disabled`.
