---
id: "001172"
title: The public list of Antragstypen gives the key
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/application_types/test_application_types_router.py:test_list_public_ok_camel_case"
implementation:
  - backend/app/modules/application_types/service.py
  - backend/app/modules/application_types/schemas.py
scope:
  - backend/app/modules/application_types
---

# The public list of Antragstypen gives the key

`GET /api/application-types` must give the `key` of every type to every caller. The `gremiumId`
must stay admin-only.

Reason: The apply URL names the type by its key (001170), so the public wizard must know the
key. The key is a slug of the German name, so it shows nothing that the name does not show.

Test: The router test checks `key` and `gremiumId` in the public view.
