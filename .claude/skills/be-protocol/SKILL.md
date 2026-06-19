---
name: be-protocol
description: Meeting minutes (Sitzungsprotokoll) — Markdown editor backing per meeting, embedded vote snippets, draft→rendering→final lifecycle, async pytex→PDF→MinIO render + gremium mailing-list send, internal vs redacted public PDF variants. Use when working on Protocol/ProtocolVoteRef, finalize/render_protocol, protocol PDF endpoints, or vote-snippet/agenda assembly in backend/app/modules/protocol.
---

# Protocol (Sitzungsprotokoll) — `backend/app/modules/protocol`

**Does:** Backs a meeting's minutes as editable Markdown, embeds vote results as snippets, and on finalize renders the document via pytex to PDF, stores it in MinIO, and mails it to the gremium mailing list — asynchronously via an arq worker (`status='rendering'`), with a synchronous fallback when Redis is absent.

**Key files:**
- `models.py` — `Protocol` (1:1 per meeting), `ProtocolVoteRef` (embedded-vote anchor); `PROTOCOL_STATUSES`.
- `router.py` — FastAPI routes; wires the `ProtocolService` with T-20 render infra (storage/mail from app.state, pytex from settings); RBAC gating.
- `service.py` — `ProtocolService`: lifecycle (`get_or_create`, `update_markdown`, `embed_votes`, `start_finalize`, `finalize`, `revert_to_draft`), agenda assembly, dual internal/public render, mail send, recipient resolution, quorum.
- `markdown.py` — DB-free Markdown builders: `build_protocol_document` (YAML frontmatter + body), `build_vote_snippet` (`> [!abstimmung]` callout), `demote_headings`, `sanitize_user_markdown` (RCE/path-traversal hardening), `protocol_variant_for`.
- `schemas.py` — camelCase wire models: `ProtocolOut`, `ProtocolPatch`, `ProtocolVotesBody`.
- `queue.py` — `ArqProtocolRenderQueue` / `protocol_render_queue_from_pool`; `PROTOCOL_RENDER_TASK_NAME = "render_protocol"`. Deliberately no `_job_id` (re-finalize after rollback must enqueue fresh).
- `../../../worker/protocol.py` — the `render_protocol` arq task: builds the service from `ctx` deps, calls `finalize`, retries on transient (`ServiceUnavailableError`) up to `pdf_max_tries`, reverts to `draft` on permanent failure, then broadcasts `meeting_state`.

**Domain / data model:**
- `protocol` — UUID pk; `meeting_id` (FK meeting, CASCADE) with `UniqueConstraint uq_protocol_meeting` (the 1:1 that makes create idempotent); `gremium_id` (FK gremium, CASCADE, indexed); `markdown` (Text, editor backing); `pdf_storage_key` / `public_pdf_storage_key` (nullable MinIO keys); `author`; `status` (Text, CheckConstraint `protocol_status` IN draft/rendering/final, default `draft`); `sent_at`; `cd_variant` (copied from gremium → selects pytex variant). TimestampMixin.
- `protocol_vote_ref` — UUID pk; `protocol_id` (FK protocol, CASCADE, indexed) + `vote_id` (FK vote, CASCADE); `UniqueConstraint uq_protocol_vote_ref(protocol_id, vote_id)` makes embedding idempotent (no duplicate snippet).
- **Lifecycle:** `draft → rendering → final`. `rendering` = finalize triggered, worker rendering in background; permanent render failure rolls back to `draft` (never stuck in `rendering`). `final` is read-only (sets `pdf_storage_key` + `sent_at`).
- Tables created on a fresh schema via `Base.metadata.create_all` (migration 0002); migration 0013 backfills them idempotently (`checkfirst`) on older schemas.

**API surface:**
- `POST /api/meetings/{meeting_id}/protocol` — create OR load (idempotent; 409 if meeting still `planned` — minutes are created on meeting start, not before). `meeting.manage`.
- `GET /api/meetings/{meeting_id}/protocol` — read (404 if none); reload/poll path used during background render. `meeting.manage` OR `meeting.view_all`.
- `PATCH /api/protocols/{protocol_id}` — update Markdown body; 409 if final/rendering. `meeting.manage`.
- `POST /api/protocols/{protocol_id}/votes` — embed votes as snippets (idempotent). `meeting.manage`.
- `POST /api/protocols/{protocol_id}/finalize` — set `rendering` + enqueue `render_protocol`; sync fallback without Redis; idempotent. `protocol.finalize`.
- `GET /api/protocols/{protocol_id}/pdf` — stream internal PDF bytes server-side. `meeting.manage` OR `meeting.view_all`.
- `GET /api/protocols/{protocol_id}/pdf/public` — stream redacted public variant (404 unless a non-public TOP exists). Same read perms.

**Conventions & gotchas:**
- **RBAC server-side, fail-closed.** Write = `meeting.manage`; finalize is split out to `protocol.finalize` (#6); read is opened additionally to `meeting.view_all`. Reads are global-permission-gated (no per-gremium scope check).
- **Source of truth for the body is the per-TOP agenda editor** when TOPs exist: `_assemble_from_agenda` stitches each `MeetingAgendaItem.body` (with `demote_headings`) + its non-cancelled `Vote` tally snippets. Only with zero agenda items does it fall back to the free-edited `protocol.markdown`.
- **TOP headings are top-level `#` with NO "TOP n:" prefix** — pytex auto-numbers sections as "TOP 1", "TOP 2". Body headings are demoted one level so they aren't counted as new TOPs.
- **Public vs internal (dual render):** if any agenda item has `non_public=True`, finalize renders BOTH a full internal PDF and a redacted public PDF (non-public TOP bodies/votes replaced by a placeholder, heading/numbering preserved). **Only the public variant is mailed.** Otherwise a single internal PDF is rendered and mailed.
- **No browser bucket links.** MinIO lives on the internal Docker network; `pdfUrl`/`publicPdfUrl` are app-relative `/api/protocols/{id}/pdf[/public]` paths streamed server-side, never presigned S3 URLs.
- **pre-commit-side-effects ordering:** pytex render runs BEFORE the commit (a compile error rolls the session back, protocol stays draft); the MinIO `put` and mail enqueue happen ONLY AFTER a successful commit, so a failed commit leaves no orphan object / stray send job.
- **Fail discipline:** storage is the deliberate on/off switch — if storage/pytex is `None` (DEV/Demo/contract-CI without MinIO), finalize still completes (`final` + mail without PDF). A transient backend failure raises `ServiceUnavailableError` (503) → session rollback → re-finalizable. pytex 4xx (bad LaTeX) → `BadRequestError` (400, scrubbed reason).
- **RCE hardening (cross-link `be-pdf`):** the body is user-written, so `sanitize_user_markdown` strips pytex's `eval`-escape (`[//]: # "EXPR"`), `\iffalse{pytex(...)}\fi`, and neutralizes absolute/`..`-traversal image paths; AND the service renders this path `trust_level="untrusted"` (eval locked + sandbox) — two independent layers. App-generated PDFs in `be-pdf` keep their `trusted` default.
- **Idempotency everywhere:** `get_or_create` uses `INSERT … ON CONFLICT (meeting_id) DO NOTHING` + re-select; `embed_votes` uses `ON CONFLICT (protocol_id, vote_id) DO NOTHING`; `start_finalize`/`finalize` no-op on `rendering`/`final`; mail dedupes via `compute_idempotency_key("protocol_finalized", id)`.
- **Mail recipients** = union of active gremium members (term window, email≠NULL, via `RecipientResolver`) ∪ configured `mail_list` extra distributors, then filtered by per-user "protocol" notification preference. PDF goes as an **attachment** (`protokoll.pdf`), not a login-gated link.
- **Variant:** gremium `cd_variant` in {`stupa`,`asta`} → pytex variant `protocol-<cd>`; otherwise `None` (pytex infers from `typ: protokoll` frontmatter).
- The worker (`worker/protocol.py`) reverts to draft and broadcasts `meeting_state` on both success and permanent failure so live followers see the status flip; the FE polls the GET endpoint (GET avoids the write rate-limit, #429).

**Related:** be-pdf, be-livevote, be-notifications, be-voting, be-files, be-admin
