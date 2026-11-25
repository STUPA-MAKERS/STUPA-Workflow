---
id: "003093"
title: Mollie has a feature switch
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# Mollie has a feature switch

Mollie must have a switch under /admin/features (`mollie`). The switch must be on until an admin
switches it off, as each feature is. While it is off, the platform must not call Mollie, each
route under `/api/mollie` and `/api/admin/mollie` must answer 404 `feature_disabled`, and the
platform must show no element of the integration. The connection and the read payments must
stay. While the feature `events` (003032) is off, the platform must show no element of the
integration either.

Reason: An admin stops the whole integration with one press and loses no setting.

Test: A backend unit test finds each route under `/api/mollie` in the feature `mollie`, switches
it off and gets `feature_disabled`.
