---
id: "000592"
title: An old German URL redirects to its English URL
kind: non-functional
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

# An old German URL redirects to its English URL

An old German URL must keep working. The frontend must redirect an old route to its new
route and keep the ID, the query and the fragment. The API must answer an old path like its
new path. The frontend must read an old query key or value like its new one.

| Old | New |
|---|---|
| `/antrag/<id>` (old magic link of one Antrag) | `/status/<id>` |
| `/protokolle`, `/protokolle/<id>` | `/protocols`, `/protocols/<id>` |
| `/barrierefreiheit` | `/accessibility` |
| `/gremien`, `/gremien/<id>` | `/committees`, `/committees/<id>` |
| `/admin/gremien`, `/admin/gremien/<id>/members`, `/admin/gremien/<id>/roles` | `/admin/committees`, `/admin/committees/<id>/members`, `/admin/committees/<id>/roles` |
| `?tab=sitzungen`, `mitglieder`, `anwesenheit`, `beschluesse` | `?tab=meetings`, `members`, `attendance`, `decisions` |
| `?gremium=<id>` | `?committee=<id>` |
| `/budget?ks=<id>` | `/budget?costCentre=<id>` |
| `/api/gremien/...` | `/api/committees/...` |
| `/api/admin/gremien/...` | `/api/admin/committees/...` |
| `/api/public/gremien` | `/api/public/committees` |
| `/api/admin/privacy/auskunft` | `/api/admin/privacy/export` |

Reason: Mails, bookmarks, printed QR codes and installed MCP servers hold the old URLs. A
broken magic link locks a guest applicant out of the Antrag.

Test: `frontend/src/app/app.routes.spec.ts`: every old route redirects to its new route with
the same ID, query and fragment.
`backend/tests/unit/test_legacy_paths.py`: every old API path answers like its new path.
