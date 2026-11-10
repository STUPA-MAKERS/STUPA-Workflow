---
id: "000592"
title: An old German URL redirects to its English URL
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/core/routing/legacy-url.serializer.spec.ts:LegacyUrlSerializer"
  - "backend/tests/unit/test_legacy_paths.py:test_the_old_path_answers_like_the_new_path"
implementation:
  - frontend/src/app/core/routing/legacy-url.serializer.ts
  - frontend/src/app/app.config.ts
  - backend/app/middleware.py
  - deploy/web/nginx.conf
scope:
  - frontend/src/app/
  - backend/app/
  - mcp/
  - deploy/web/
---

# An old German URL redirects to its English URL

An old German URL must keep working. The frontend must redirect an old route to its new
route and keep the ID, the query and the fragment. The API must answer an old path like its
new path. The frontend must read an old query key or value like its new one. The old link of
one Antrag must open the Antrag in the list of the own Anträge with its fragment, because the
e-mail login replaces the view of one Antrag by link (`F/applications/applications/000588`).

| Old | New |
|---|---|
| `/antrag/<id>` (old link of one Antrag) | `/my-applications/<id>` |
| `/protokolle`, `/protokolle/<id>` | `/protocols`, `/protocols/<id>` |
| `/barrierefreiheit` | `/accessibility` |
| `/gremien`, `/gremien/<id>` | `/committees`, `/committees/<id>` |
| `/admin/gremien`, `/admin/gremien/<id>/members`, `/admin/gremien/<id>/roles` | `/admin/committees`, `/admin/committees/<id>/members`, `/admin/committees/<id>/roles` |
| `?tab=sitzungen`, `mitglieder`, `anwesenheit`, `beschluesse` | `?tab=meetings`, `members`, `attendance`, `decisions` |
| `?gremium=<id>` | `?committee=<id>` |
| `/budget?ks=<id>` | `/budget?costCentre=<id>` |
| `/api/gremien/...` | `/api/committees/...` |
| `/api/admin/gremien/...` | `/api/admin/committees/...` |
| `/api/meetings/gremien` | `/api/meetings/committees` |
| `/api/public/gremien` | `/api/public/committees` |
| `/api/admin/privacy/auskunft` | `/api/admin/privacy/export` |
| `/voting/beamer`, `/voting/beamer/<id>` | `/voting/projector`, `/voting/projector/<id>` |
| `/api/admin/gremium-roles/...` | `/api/admin/committee-roles/...` |
| `/api/admin/gremium-membership-mappings/...` | `/api/admin/committee-membership-mappings/...` |
| `/api/admin/gremium-role-mappings/...` | `/api/admin/committee-role-mappings/...` |
| `/api/meetings/<id>/protokollant-handover` | `/api/meetings/<id>/minute-taker-handover` |
| `/api/ws/meetings/<id>/beamer` | `/api/ws/meetings/<id>/projector` |
| `/status?app=<id>&t=<token>` | `/my-applications/<id>#t=<token>` |

Reason: Mails, bookmarks, printed QR codes and installed MCP servers hold the old URLs. A
broken magic link locks a guest applicant out of the Antrag.

Test: `frontend/src/app/core/routing/legacy-url.serializer.spec.ts`: every old URL reads as
its new URL with the same ID, query and fragment. `backend/tests/unit/test_legacy_paths.py`:
every old API path answers like its new path.
