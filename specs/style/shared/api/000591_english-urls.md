---
id: "000591"
title: Every URL is in English
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/
  - backend/app/
  - mcp/
  - deploy/web/
---

# Every URL is in English

Every path segment, query key and query value of a URL must be an English word. This applies
to the routes of the frontend, the paths of the API, the links in mails and the links that the
backend sends. The texts that a page shows stay in the language of the user.

Reason: A German slug next to an English one makes the URLs of the platform inconsistent, and
the code, the API and the specs use English names.

Test: `frontend/src/app/app.routes.spec.ts`: no route path holds a German word from the list
of the old paths in `NF/compatibility/links/000592`.
