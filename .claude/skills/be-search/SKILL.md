---
name: be-search
description: Global search behind the command palette. One GET /api/search?q= fans out to seven sources (applications, meetings, invoices, expenses, cost centres, Gremien, people). Each source reuses the gate and the listing of its own module, so a hit is never more than the module list shows. Covers SearchService, SearchHit/SearchResults, HIT_URL, PER_KIND, the trigram/ILIKE helper app/search.py (trigram_rank, escape_like, dialect_of) and the frontend command palette. Use when working on the global search, a new search source, hit titles/subtitles/URLs, or trigram ranking in backend/app/modules/search and backend/app/search.py.
---

# Global search — `backend/app/modules/search`

**Does:** Answers the command palette (Ctrl+K) with one flat list of hits for one query. The service has NO authorization of its own: each source calls the listing that already serves the module's own endpoint, with the same scope arguments as that router. A hit can only appear when the caller could reach the record through the module list.

**Key files:**
- `router.py` — `GET /search`. It needs a principal (401 otherwise) and caps `q` at 200 characters (a DoS bound for the trigram scan) and `lang` at 8.
- `service.py` — `SearchService.search` and one private source per kind (`_applications`, `_meetings`, `_invoices`, `_expenses`, `_budgets`, `_gremien`, `_principals`). The module constants: `PER_KIND = 5`, `MIN_QUERY_LENGTH = 2`, `UNTITLED`, `UNNAMED` and `GREMIUM_SUBTITLE` (each de/en), `HIT_URL`.
- `schemas.py` — `SearchKind` (`Literal` of the seven kinds), `SearchHit` (`kind`, `id`, `title`, `subtitle`, `url`, `archived`), `SearchResults` (`hits`, `truncated`, `failed`).
- `../../search.py` (`app/search.py`, shared) — `trigram_rank(q, columns, dialect=...)` gives `(where, rank)`: Postgres `word_similarity` with the threshold 0.3 (GIN trigram indexes), any other dialect an `ILIKE` with the constant rank `0.0`. `escape_like` escapes `\`, `%` and `_`. `dialect_of(session)` gives `postgresql` without a bound engine. Other list services (applications, budget, principals) use the same helper.
- Frontend: `frontend/src/app/features/search/` — `command-palette.component` (groups by `kind`, "Seiten" from `page-index.service`, highlight, archived mark, the truncated note), `command-palette.service`, `shortcut.ts`.

**Sources and their gates:**
- `application` — `ApplicationsService.list_applications`. With `application.read` or `application.read_all` every application, else the own ones plus the committee read scope. Without a global read, no search over the PII field values of another application (`hide_pii_in_search`, O21). Archived rows are included (`archived=None`) and carry `archived: true`. Subtitle: the state label in `lang`.
- `meeting` — `MeetingService.list_timeline(direction="past")`, scoped to the visible Gremien. Subtitle: the Gremium name.
- `invoice`, `expense` — one of `budget.view`/`budget.structure`/`budget.book` (the gate of `GET /api/invoices` and `/api/expenses`). Subtitle: the amount and the supplier or correspondent.
- `budget` — own query on `Budget.name`/`path_key`, without `hidden_in_budget` nodes. Without a budget read permission only the nodes whose `view_gremium_id` is a Gremium of the caller (as `GET /api/budgets`). Subtitle: `path_key`.
- `gremium` — own query on `Gremium.name`/`slug`, only with `admin.gremien` or `admin.users` (the hit links to the members page, which only an admin can open). Subtitle: the kind only, "Gremium" / "Committee" (D10); the slug is an internal key.
- `principal` — `ConfigService.search_principals`, with `admin.users` or `admin.gremien`. Title: the name, else the e-mail, else "Ohne Namen" / "No name" (`UNNAMED`, D7; never the `sub`); subtitle: the e-mail when a name exists.

**API surface:**
- `GET /api/search?q=&lang=` — P(any principal). Returns `SearchResults`. A query shorter than 2 characters (after trim) returns an empty result, never an error. The palette calls the route on each key press.

**Conventions & gotchas:**
- **Never add a gate here.** A new source wires the existing listing of its module with the same scope arguments as that router. Then a permission change in the module reaches the palette by itself. A source with its own query (cost centres, Gremien) must copy the read scope of the module router, and its docstring says which one.
- **The gate comes before the query.** A source without the permission returns `[]` without a database call (see `test_a_gated_source_answers_nothing_without_its_permission`).
- **Sequential, not gathered.** The sources share one `AsyncSession`, which is not safe for concurrent use.
- **One source cannot empty the palette.** A source that raises is logged and named in `failed`; the others still answer.
- **Cap per kind.** Each source asks for `PER_KIND + 1` rows. More than `PER_KIND` sets `truncated`, and the client says that the list is not complete.
- **A hit is flat and resolved on the server.** Titles and subtitles are final text in `lang` (German fallback). A nameless record reads "Ohne Titel" / "Untitled", never its id ([[no-uuids-in-ui]]).
- **`HIT_URL` names the record.** Every template holds `{id}`: a path segment where the record has a page, a query filter where it does not (`/invoices?id=`, `/budget?ks=`, `/admin/users?q=<sub>`). A new kind needs an entry; `test_every_kind_has_a_url_that_names_the_record` checks it.
- `q` is always a bound parameter. `escape_like` makes a typed `%` or `_` a literal.

**Related:** be-applications, be-livevote, be-budget, be-admin, frontend
