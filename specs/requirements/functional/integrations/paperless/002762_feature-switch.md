---
id: "002762"
title: Paperless has a feature switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/features/test_features_api.py:test_a_feature_that_is_off_answers_feature_disabled_to_the_admin"
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_while_the_feature_is_off_the_worker_calls_nothing"
  - "backend/tests/unit/modules/site_config/test_features.py:test_every_route_of_the_app_is_in_the_expected_feature"
  - "frontend/src/app/core/api/paperless.service.spec.ts:PaperlessService"
implementation:
  - backend/app/modules/site_config/features.py
  - backend/app/feature_routes.py
  - backend/worker/paperless.py
  - frontend/src/app/core/features/feature.service.ts
  - frontend/src/app/core/api/paperless.service.ts
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
