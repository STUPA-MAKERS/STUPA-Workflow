---
id: "003013"
title: Bestellungen have a feature switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "backend/tests/unit/modules/site_config/test_features.py:test_the_route_table_names_the_features_of_a_route"
  - "backend/tests/integration/modules/features/test_features_api.py:test_orders_go_off_with_budget_and_with_their_own_switch"
  - "frontend/src/app/pages/admin/features/features.component.spec.ts:FeaturesComponent"
implementation:
  - backend/app/modules/site_config/features.py
  - backend/app/feature_routes.py
  - frontend/src/app/core/features/feature.service.ts
  - frontend/src/app/pages/admin/features/features.component.ts
scope:
  - backend/app/
  - frontend/src/app/
---

# Bestellungen have a feature switch

Bestellungen must have a switch under /admin/features (`orders`). The switch must be on until
an admin switches it off, as each feature is. `Bestellungen` needs `Budget` (000760): while
`Budget` is off, `Bestellungen` must be off, and its switch must be locked with the text that
names `Budget`, as the switch of `Rechnungen` is.

While `Bestellungen` is off, every route of a Bestellung must answer 404 `feature_disabled`:
the routes under `/api/orders`, the Bestellungen of an Antrag and the Bestellungen of an
invoice. The platform must show no element of the feature: the page "Bestellungen" and its
entry in the navigation, the action "Bestellung anlegen" and the Bestellungen in "Verknüpft"
of an Antrag, the Bestellungen of an invoice, the link kind, the hits of the search and the
nodes of the graph. The stored Bestellungen, their files
and the entries of the history of an Antrag must stay. When the switch goes on again, each
Bestellung must show as before.

Reason: A student government that does not buy through the platform must not see a page and
actions that it does not use. One press must be enough, and it must lose no data.

Test: A backend unit test finds each route of a Bestellung in the feature `orders`. An
integration test switches `orders` off and gets `feature_disabled` from the list. A frontend
unit test finds the switch on the page of the features, locked while `Budget` is off.
