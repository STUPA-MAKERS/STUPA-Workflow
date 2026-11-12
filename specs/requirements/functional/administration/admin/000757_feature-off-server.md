---
id: "000757"
title: A feature that is off is closed on the server
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/features/test_features_api.py:test_a_feature_that_is_off_answers_feature_disabled_to_the_admin"
  - "backend/tests/unit/test_feature_gate.py:test_a_route_of_a_feature_that_is_off_is_not_found"
  - "backend/tests/unit/modules/site_config/test_features.py:test_every_route_of_the_app_is_in_the_expected_feature"
  - "backend/tests/unit/worker/test_worker_features.py:test_a_job_of_a_feature_that_is_off_does_nothing"
implementation:
  - backend/app/feature_routes.py
  - backend/app/main.py
  - backend/worker/features.py
  - backend/app/modules/site_config/features.py
scope:
  - backend/app/modules
  - frontend/src/app
  - backend/worker
  - mcp
---

# A feature that is off is closed on the server

While a feature is off, each API route of the feature must answer 404 with the problem code
`feature_disabled`, for every person and for every token. A job of the feature that sends a
mail, fetches a source or changes a record must not run. A retention job must run on, because
the duties of data protection do not depend on a switch. The MCP server must pass the 404 on. The answer must not
depend on a permission, so an admin also gets the 404.

Reason: The server decides on access, not the UI. A feature that is only hidden stays open
through the API and through an agent.

Test: `backend/tests/integration/modules/features/test_features_api.py` switches each feature off
and calls one read route and one write route of the feature as admin. Each call gets 404 with
`feature_disabled`. `backend/tests/unit/modules/site_config/test_features.py` finds every route of
the app in the expected feature. `backend/tests/unit/worker/test_worker_features.py` runs each job of
a feature that is off and finds that it opens no further session.
