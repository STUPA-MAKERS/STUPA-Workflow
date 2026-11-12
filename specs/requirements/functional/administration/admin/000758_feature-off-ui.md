---
id: "000758"
title: A feature that is off does not show in the UI
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/layout/nav.service.spec.ts:NavService"
  - "frontend/src/app/core/features/feature.guard.spec.ts:featureMatch"
  - "frontend/src/app/features/search/page-index.service.spec.ts:PageIndexService"
  - "backend/tests/integration/modules/features/test_features_api.py:test_a_switch_keeps_the_records_and_the_search_follows_it"
  - "backend/tests/integration/modules/calendar/test_calendar_features.py:test_the_calendar_omits_the_entries_of_a_feature_that_is_off"
implementation:
  - frontend/src/app/core/features/feature.service.ts
  - frontend/src/app/core/features/feature.guard.ts
  - frontend/src/app/layout/nav.service.ts
  - frontend/src/app/app.routes.ts
  - backend/app/modules/search/service.py
  - backend/app/modules/calendar/entries.py
  - backend/app/modules/todos/links.py
scope:
  - frontend/src/app
  - backend/app/modules/search
  - backend/app/modules/site_config
---

# A feature that is off does not show in the UI

While a feature is off, the UI must not show its navigation entry, its pages, its admin pages, its
entries in the command palette and its notification settings. A route of the feature must show the
page `Seite nicht gefunden`. The global search must not return hits of the feature.

Another page must leave out the parts that belong to the feature and must not show an empty
section or a dead link in their place. Examples: the Kalender omits the meetings while `Sitzungen`
is off and the due cards while `Boards` is off. The Antrag omits the Kostenstelle while `Budget` is
off. The start page omits the tiles of a feature that is off.

The public site configuration must name the state of each feature, so that the public pages follow
the switches without a session.

Reason: A person must not find a way into a part that the student body does not use.

Test: `frontend/src/app/layout/nav.service.spec.ts` switches each feature off and finds no
navigation entry of it. `frontend/src/app/core/features/feature.guard.spec.ts` finds the guard on
the routes of each feature, and the guard does not match while the feature is off, so the route
shows the not-found page. `backend/tests/integration/modules/features/test_features_api.py` finds no
search hit of a feature that is off.
