---
id: "000980"
title: The embedded PDFs belong to the feature Sitzungen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/feature_routes.py
scope:
  - backend/app/feature_routes.py
  - backend/app/modules/media
---

# The embedded PDFs belong to the feature Sitzungen

The routes under `/api/media/documents` must answer 404 `feature_disabled` while `Sitzungen` is
off (§F/administration/admin/000757).

Reason: An embedded PDF exists only in a protocol. Without the rule its route stays open while
each other route of the protocols is closed.

Test: A backend unit test finds the feature `meetings` for the path templates of both routes.
