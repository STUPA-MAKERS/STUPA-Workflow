---
id: "000762"
title: The admin page Funktionen holds the feature switches
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/features/test_features_api.py:test_the_switches_need_their_own_permission"
  - "backend/tests/integration/modules/features/test_features_api.py:test_a_save_writes_a_version_and_an_audit_entry_that_a_revert_sets_back"
  - "frontend/src/app/pages/admin/features/features.component.spec.ts:FeaturesComponent"
implementation:
  - backend/app/modules/admin/router.py
  - backend/app/modules/admin/site_config_service.py
  - backend/app/shared/permissions.py
  - backend/migrations/versions/3d95c7b1f9e6_admin_features_permission.py
  - frontend/src/app/pages/admin/features/features.component.ts
  - frontend/src/app/pages/admin/admin-frame/admin-pages.ts
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

Test: `backend/tests/integration/modules/features/test_features_api.py` saves the switches without
`admin.features` and gets 403. A second test saves a switch, finds the new configuration version
and the audit entry, and reverts the entry.
