---
name: be-protocol
description: Protocol — a Markdown editor backing per meeting, embedded vote snippets, and the draft→rendering→final lifecycle. Covers the async typst→PDF→MinIO render, the gremium mailing-list send, and internal vs redacted public PDF variants. Use when working on Protocol/ProtocolVoteRef, finalize/render_protocol, protocol PDF endpoints, or vote-snippet/agenda assembly in backend/app/modules/protocol.
---

# Protocol — `backend/app/modules/protocol`

**Does:** Backs the protocol of a meeting as editable Markdown and embeds vote results as snippets. On finalize it renders the document to PDF via the typst render service, stores the PDF in MinIO, and mails it to the gremium mailing list. The render runs asynchronously in an arq worker (`status='rendering'`). Without Redis it falls back to a synchronous render.

**Key files:**
- `models.py` — `Protocol` (1:1 per meeting), `ProtocolVoteRef` (embedded-vote anchor), and `PROTOCOL_STATUSES`.
- `router.py` — the FastAPI routes. It wires `ProtocolService` to the T-20 render infrastructure (storage and mail from app.state, typst from settings) and applies the RBAC gating.
- `service.py` — `ProtocolService`: lifecycle (`get_or_create`, `update_markdown`, `embed_votes`, `start_finalize`, `finalize`, `revert_to_draft`), agenda assembly, dual internal/public render, mail send, recipient resolution, quorum.
- `markdown.py` — DB-free Markdown builders: `build_protocol_document` (YAML frontmatter + body), `build_vote_snippet` (`> [!abstimmung]` callout), `demote_headings`, `sanitize_user_markdown` (RCE/path-traversal hardening), `protocol_variant_for`.
- `schemas.py` — camelCase wire models: `ProtocolOut`, `ProtocolPatch`, `ProtocolVotesBody`.
- `queue.py` — `ArqProtocolRenderQueue` / `protocol_render_queue_from_pool` with `PROTOCOL_RENDER_TASK_NAME = "render_protocol"`. It sets no `_job_id` on purpose, because a re-finalize after a rollback must enqueue a fresh job.
- `../../../worker/protocol.py` — the `render_protocol` arq task: builds the service from `ctx` deps, calls `finalize`, retries on transient (`ServiceUnavailableError`) up to `pdf_max_tries`, reverts to `draft` on permanent failure, then broadcasts `meeting_state`.

**Domain / data model:**
- `protocol` — UUID pk, `meeting_id` (FK meeting, CASCADE) with `UniqueConstraint uq_protocol_meeting`, `gremium_id` (FK gremium, CASCADE, indexed), `markdown` (Text, editor backing), `pdf_storage_key` / `public_pdf_storage_key` (nullable MinIO keys), `author`, `status` (Text, CheckConstraint `protocol_status` IN draft/rendering/final, default `draft`), `sent_at`, `cd_variant` (copied from gremium → selects the render variant), plus TimestampMixin. The unique constraint is the 1:1 that makes create idempotent.
- `protocol_vote_ref` — UUID pk, `protocol_id` (FK protocol, CASCADE, indexed) + `vote_id` (FK vote, CASCADE). `UniqueConstraint uq_protocol_vote_ref(protocol_id, vote_id)` makes embedding idempotent (no duplicate snippet).
- **Lifecycle:** `draft → rendering → final`. `rendering` means finalize started and the worker renders in the background. A permanent render failure rolls back to `draft`, so the protocol never sticks in `rendering`. `final` is read-only and sets `pdf_storage_key` + `sent_at`.
- Migration 0001 (the baseline) creates the tables via `Base.metadata.create_all`, idempotently on both a fresh and an existing schema.

**API surface:**
- `POST /api/meetings/{meeting_id}/protocol` — create OR load, idempotent. It answers 409 while the meeting is still `planned`, because the service creates the protocol when the meeting starts, not before. write access (`MeetingService.can_write`: `session.manage` or `protocol.write` in the Gremium, the assigned protokollant, or admin).
- `GET /api/meetings/{meeting_id}/protocol` — read, 404 if none. The frontend polls this path during a background render. read access (`assert_can_read`: Gremium member, pool substitute, delegation recipient, `meeting.view_all`, admin).
- `PATCH /api/protocols/{protocol_id}` — update the Markdown body. It answers 409 when the status is final or rendering. Write access.
- `POST /api/protocols/{protocol_id}/votes` — embed votes as snippets (idempotent). Write access.
- `POST /api/protocols/{protocol_id}/finalize` — set `rendering` and enqueue `render_protocol`. Without Redis it renders synchronously. The call is idempotent. `MeetingService.can_finalize`: write access AND the GREMIUM permission `protocol.finalize` in the Gremium of the meeting (or admin). Otherwise 403 `Missing permission(s): protocol.finalize`.
- `GET /api/protocols/{protocol_id}/pdf` — stream the internal PDF bytes server-side. Read access.
- `GET /api/protocols/{protocol_id}/pdf/public` — stream the redacted public variant (404 unless a non-public agenda item exists). Same read perms.

**Conventions & gotchas:**
- **RBAC server-side, fail-closed, per Gremium.** The service delegates every check to `MeetingService` (`can_write`, `can_finalize`, `assert_can_read`), so the protocol and the live stack share one rule and the OAuth scope cap. There is no global `meeting.manage` or `protocol.finalize` any more (migration `3a0b9672fcba`, decisions O2/O7). The forced Gremium roles `vorstand` and `manager` hold `protocol.finalize`; a custom role with `session.manage` but without it can write but gets 403 on finalize. The meeting payload carries `canFinalize`, and the frontend auto-finalizes on close only when it is true.
- **Source of truth for the body is the per-agenda-item editor** when agenda items exist: `_assemble_from_agenda` stitches each `MeetingAgendaItem.body` (with `demote_headings`) + its non-cancelled `Vote` tally snippets. It falls back to the free-edited `protocol.markdown` only when the meeting has zero agenda items.
- **Agenda item headings are top-level `#` with NO "TOP n:" prefix** — the renderer numbers the sections automatically as "TOP 1", "TOP 2". The builder demotes body headings one level, so the renderer does not count them as new agenda items.
- **Public vs internal (dual render):** if any agenda item has `non_public=True`, finalize renders BOTH a full internal PDF and a redacted public PDF. The redacted variant replaces the non-public agenda item bodies and votes with a placeholder and keeps the heading and the numbering. Only the **public** variant goes to the mailing list. Otherwise finalize renders one internal PDF and mails it.
- **No browser bucket links.** MinIO lives on the internal Docker network. `pdfUrl`/`publicPdfUrl` are app-relative `/api/protocols/{id}/pdf[/public]` paths that the API streams server-side. They are never presigned S3 URLs.
- **pre-commit-side-effects ordering:** the typst render runs BEFORE the commit. A render error rolls the session back and the protocol stays draft. The MinIO `put` and the mail enqueue happen ONLY AFTER a successful commit. A failed commit therefore leaves no orphan object and no stray send job.
- **Fail discipline:** storage is the deliberate on/off switch — if storage/typst is `None` (DEV/Demo/contract-CI without MinIO), finalize still completes (`final` + mail without PDF). A transient backend failure raises `ServiceUnavailableError` (503) → session rollback → re-finalizable. typst 4xx (e.g. a malformed formula) → `BadRequestError` (400, scrubbed reason).
- **Injection hardening (cross-link `typst`):** the body is user-written, but the typst render service converts it into JSON data before Typst sees it, so no part of it runs as code. `sanitize_user_markdown` stays as defense in depth: it strips the former pytex `eval`-escape (`[//]: # "EXPR"`) and `\iffalse{pytex(...)}\fi`, and neutralizes absolute and `..`-traversal image paths.
- **Idempotency everywhere.** `get_or_create` uses `INSERT … ON CONFLICT (meeting_id) DO NOTHING` plus a re-select. `embed_votes` uses `ON CONFLICT (protocol_id, vote_id) DO NOTHING`. `start_finalize`/`finalize` no-op on `rendering`/`final`. The mail dedupes via `compute_idempotency_key("protocol_finalized", id)`.
- **Mail recipients** = union of active gremium members (term window, email≠NULL, via `RecipientResolver`) ∪ configured `mail_list` extra distributors, then filtered by per-user "protocol" notification preference. PDF goes as an **attachment** (`protokoll.pdf`), not a login-gated link.
- **Variant:** a gremium `cd_variant` in {`stupa`,`asta`} selects the render variant `protocol-<cd>` (default logos). Any other value gives `None`, and the service reads the logos from the `gremium` frontmatter key.
- The worker (`worker/protocol.py`) reverts to draft and broadcasts `meeting_state` on both success and permanent failure, so live followers see the status flip. The frontend polls the GET endpoint, because GET avoids the write rate-limit (#429).

**Related:** be-pdf, be-livevote, be-notifications, be-voting, be-files, be-admin
