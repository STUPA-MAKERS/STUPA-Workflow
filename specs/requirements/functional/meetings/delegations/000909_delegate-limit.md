---
id: "000909"
title: A delegate holds a limited number of delegations
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/delegations/test_delegate_limit_live.py:test_one_delegation_more_than_the_limit_conflicts"
  - "backend/tests/unit/modules/delegations/test_delegations_service_cov.py:test_create_over_the_limit_conflict"
implementation:
  - backend/app/modules/delegations/service.py
  - backend/app/modules/gremien/models.py
  - backend/app/modules/admin/schemas.py
  - backend/migrations/versions/d81b6e42a9f3_delegation_limit.py
  - frontend/src/app/pages/admin/committees/gremium-dialog/gremium-dialog.component.ts
scope:
  - backend/app/modules/delegations
  - backend/app/modules/gremien
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A delegate holds a limited number of delegations

A Gremium must have the setting `delegationMaxPerDelegate`. In one meeting a delegate must not
hold more delegations than this value. A further delegation must answer 409 `delegate_limit`. A
pool seat must not count.

Reason: The Organisationssatzung lets a member hold at most two Stimmrechtsübertragungen.

Test: An integration test that creates one delegation more than the limit.
