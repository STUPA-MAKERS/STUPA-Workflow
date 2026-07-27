---
name: async-protocol-render
description: "DONE — protocol PDF finalize renders async in the worker (commits bb94eb4 BE + 11e220b FE), only deploy and restart of the running stack pending"
metadata: 
  node_type: memory
  type: project
---

**DONE 2026-06-10, pushed to `main`:** `bb94eb4` (backend) + `11e220b` (frontend).

Implementation, as planned. `Protocol.status` gained `rendering`. Migration
`0011_protocol_rendering_status` widens the CheckConstraint, and its downgrade resets
rendering→draft first. `POST /protocols/{id}/finalize` calls `ProtocolService.start_finalize`,
which flips draft→rendering (committed), enqueues `render_protocol` through `protocol/queue.py`,
broadcasts `meeting_state` and returns at once. The enqueue passes **no** `_job_id` on purpose,
because a job id would dedupe against kept results after a revert. The status guards a double
enqueue instead. Without Redis the call falls back to the old synchronous path and reverts on
error, so a protocol never stays stuck in rendering. The worker
`worker/protocol.py::render_protocol` (registered in `worker/main.py`) reuses
`ProtocolService.finalize`. A transient error raises `arq.Retry` with linear backoff up to
`pdf_max_tries`. Any permanent failure calls `revert_to_draft` and logs, the mail enqueue
included, because the user chose atomic behavior. The worker broadcasts `meeting_state` after
done or revert through `RedisBroker(ctx['redis'])`. An edit while rendering returns 409
(`_ensure_draft`). FE: `Protocol.isLocked` (status!=='draft') gates editor, agenda, votes and
finalize. A warning badge shows `meetings.protocol.rendering`. The WS `meeting_state` event
reloads the protocol (canWrite only), with a 4s poll fallback
(`watchRendering`/`applyProtocolUpdate`). A rendering→draft change shows the finalizeFailed
toast. Tests: 55 protocol BE tests green (`backend/.venv` created to run pytest locally). FE
typecheck, lint and tests green except pre-existing failures (mapApplication budgetId,
flow-editor a11y `listWebhooks`, 3 lint unused-vars).

**2026-06-11 feedback round (all fixed, pushed `069aa34`/`c0a318f`/`d42a193`):** the real render
failure came from the pytex image, which lacked `inkscape` for the SVG→PDF logo conversion
(`protocol-asta` uses ASTA.svg). `write_inline_logos` skipped the assets and tectonic answered
400. The fix is `pytex/inkscape-shim.sh` (rsvg-convert behind the inkscape CLI) plus
`librsvg2-bin` in the Dockerfile, verified end-to-end (200, 21 KB PDF). The 413 answers came from
the 4-MiB default body cap, now `PYTEX_MAX_BODY_BYTES=33554432` in `deploy/.env`. The
user-visible "vote error + result missing" was downstream: the rendering→draft revert toast fired
when the flow transition of the vote broadcast meeting_state. New: a re-finalize button (meeting
closed + protocol draft), vote status `cancelled` (migration 0012, non-branch exits cancel open
votes, and the flow editor now draws manual exits from vote nodes), and the transition
`requiresAction` flag (migration 0013, tasks-tab filter).

**Still pending (the user must do this):** rebuild and restart the stack with
`cd deploy && docker compose build api worker web migrator && docker compose up -d migrator api worker web`.
That applies migrations 0011–0013. The pytex container is already rebuilt and verified. Then
retest finalize on meeting "Test". Flows whose transition colors predate `950341e` still need a
re-save. See [[antragsplattform-backlog]].
