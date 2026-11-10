---
id: "000591"
title: Every URL is in English
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/core/routing/legacy-url.serializer.spec.ts:LegacyUrlSerializer"
implementation:
  - frontend/src/app/app.routes.ts
  - backend/app/
  - mcp/antragsplattform_mcp/tools/
scope:
  - frontend/src/app/
  - backend/app/
  - mcp/
  - deploy/web/
---

# Every URL is in English

Every path segment, query key and query value of a URL must be an English word. This applies
to the routes of the frontend, the paths of the API, the links in mails and the links that the
backend sends. The texts that a page shows stay in the language of the user. A query key of
the API follows the name of its field (`S/shared/api/000039`), so `gremiumId` stays.

Reason: A German slug next to an English one makes the URLs of the platform inconsistent, and
the code, the API and the specs use English names.

Test: `frontend/src/app/core/routing/legacy-url.serializer.spec.ts`: no route path holds an
old German path of `NF/compatibility/links/000592`.
