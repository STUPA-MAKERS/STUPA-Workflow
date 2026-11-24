---
name: be-webhooks
description: Outbound event webhooks — a fixed event catalog, per-webhook event subscriptions with chosen payload fields and Gremium/Antragsart/target-status filters, SSRF-guarded HMAC-SHA256-signed HTTP POST delivery via the arq deliver_webhook worker and the enqueue_pending_webhooks cron. Use when working on webhook events, emit_event, the catalog, payload fields, dispatch, SSRF guard, signing, retry/dead-letter, the test delivery or the /api/admin/webhooks CRUD in backend/app/modules/webhooks.
---

# Webhooks (outbound event dispatch) — `backend/app/modules/webhooks`

**Does:** Delivers signed outbound HTTP webhooks for domain events. A webhook subscribes to events of a fixed catalog and chooses per event the fields of its `data` object (§F/integrations/webhooks/002410-002417). A domain module calls `emit_event` in the transaction of its change; it adds one `pending` delivery per subscribed webhook whose filters pass, with the body built at that moment. The worker cron `enqueue_pending_webhooks` (every 10 s) hands each new delivery to the `deliver_webhook` job. Delivery re-resolves DNS and runs the SSRF guard at send-time, HMAC-signs, POSTs without redirects and writes back status, attempts and backoff. The flow has no `webhook` action any more.

**Key files:**
- `catalog.py` — `EVENTS` (16 events: `application.created/updated/transition/archived`, `comment.created`, `vote.opened/closed`, `meeting.created/started/closed`, `protocol.finalized`, `booking.created`, `invoice.created`, `ticket.created`, `ticket.message`, `ticket.status`; the three ticket events carry the Gremium of the Bereich for the Gremium filter, `tickets/webhook_fields.py`), per event `id_keys` and `fields` (`FieldSpec(key, example, personal)`), `TEST_EVENT = "webhook.test"`, `example_payload`. The table in the protocol spec P/integrations/webhooks/000963 mirrors it.
- `events.py` — `WebhookEvent(name, ids, fields, gremium_id, type_id, state_key)`, `emit_event`, `active_webhooks` (the unit conftest stubs it to `[]`; marker `real_webhooks`), `subscribed_fields`, `build_body`. Imports no domain module: the caller passes a `fields()` coroutine that reads its own tables, called at most once and only when a webhook chose a field.
- Field builders live in the emitting modules: `applications/webhook_fields.py` (`emit_application_event`, `emit_transition_event`, helpers `link`/`ref`/`money`/`label_of`), `voting/webhook_fields.py`, `livevote/webhook_fields.py`, `protocol/webhook_fields.py`, `budget/webhook_fields.py`, `tickets/webhook_fields.py`. Emit sites: applications create/edit/archive/comment, `FlowService` transition fire, voting open/close (vote, election, poll), meeting create/start/close, protocol render final, expense create, transfer create, invoice create, ticket report.
- `service.py` — `WebhookService`: `enqueue_pending` (cron sweep: `pending`, 0 attempts, older than 5 s) + `deliver` (worker side; a row already `ok`/`dead` gives `gone`), status classification, retry/backoff/dead-letter, `DeliveryOutcome`.
- `app/shared/ssrf.py` (shared with `be-avatars`, kept at 100 % branch coverage by its own entry in `[tool.coverage_critical]`) — `assert_allowed_url`, `pin_url`, `_unmap`, `SsrfError`, injectable `Resolver`
- `signing.py` — HMAC-SHA256 over `"{timestamp}.{body}"`, `canonical_body`, `build_headers`. Header names `X-Signature`/`X-Timestamp`/`X-Webhook-Event`
- `queue.py` — `WebhookQueue` Protocol + `ArqWebhookQueue`. `WEBHOOK_TASK_NAME="deliver_webhook"`, job id `webhook:<delivery_id>` (coalesces duplicate enqueues)
- `worker/webhook.py` (sibling, not in module dir) — arq task `deliver_webhook` and cron `enqueue_pending_webhooks`. Maps `retry`→`arq.Retry`, no-redirect httpx client
- Models live in `app/modules/webhooks/models.py`. Schemas live in `app/modules/admin/schemas.py` (`WebhookSubscription` checks events and fields against the catalog). The CRUD router lives in `app/modules/admin/router/webhooks_router.py`, the service in `app/modules/admin/service/webhooks.py`.

**Domain / data model:**
- `Webhook` (table `webhook`): `name`, `url`, `secret` (LargeBinary, server-generated `secrets.token_bytes(32)`, never returned/logged), `active`, `subscriptions` (JSONB list of `{event, fields}`), `gremium_ids`, `type_ids` (JSONB UUID strings), `state_keys` (JSONB status keys of the target state of `application.transition`). An empty filter list lets every value pass; an event without the value passes too.
- `WebhookDelivery` (table `webhook_delivery`): `webhook_id` (FK CASCADE), `event`, `payload` (JSONB, the final body), `status` ∈ `pending|ok|failed|dead` (CHECK), `attempts`, `idempotency_key` (NULL for event deliveries), `last_at`, `response_code`, `created_at`. Unique `(webhook_id, idempotency_key)`.
- Migration `08e0c0134332` moved each flow `webhook` action of the active flow into an `application.transition` subscription with the target state keys, and removed the actions.

**API surface:** (admin router, permission `webhook.manage`)
- `GET /api/admin/webhooks` — list (`webhook.manage` OR `flow.configure`)
- `POST /api/admin/webhooks` — create (201, secret auto-generated)
- `PATCH /api/admin/webhooks/{webhook_id}` — update (a given list replaces the stored one)
- `DELETE /api/admin/webhooks/{webhook_id}` — delete with the deliveries
- `GET /api/admin/webhooks/catalog` — the events with ID keys, fields, `personal` and example values (dialog + preview)
- `POST /api/admin/webhooks/{webhook_id}/test` — 202 `{deliveryId}`, event `webhook.test`; 409 `webhook_inactive`
- `GET /api/admin/webhooks/delivery-status` — newest delivery state per webhook

**Conventions & gotchas:**
- The SSRF guard runs **at send-time in the worker**, not at config time. To defend against DNS rebinding, it resolves **all** A/AAAA records. One non-global record blocks the whole delivery. `_unmap` unwraps IPv4-mapped (`::ffff:`), 6to4 (`2002::/16`) and NAT64 (`64:ff9b::/96`) addresses. An embedded private or metadata IPv4 therefore cannot slip through as a "global" IPv6. After validation, `pin_url` rewrites the host to the validated IP and carries the original `Host`/SNI. That removes the resolve→connect TOCTOU.
- The signature covers `"{timestamp}.{body}"` (Stripe-style). The HMAC includes the timestamp, which gives replay protection. The module **never logs the `secret`**.
- SSRF block = permanent → delivery goes straight to `dead`, **no retry**, and the log line omits host/IP (no internal topology in logs). 3xx (no redirect is followed) and 4xx → `dead` (non-retryable). 1xx/5xx/timeout/transport → `failed`+retry with exponential backoff (`webhook_retry_backoff_seconds * 2^(n-1)`) until `webhook_max_tries`, then `dead`.
- Worker POSTs with `follow_redirects=False` and reads the response body **streamed, capped at 64 KiB** (only the status code matters) to avoid OOM from a hostile receiver.
- Idempotency: the arq job key `webhook:<delivery_id>` coalesces duplicate enqueues of the sweep, and `deliver` skips a row that is already `ok` or `dead`. An event is emitted once in its transaction, and a rollback removes its deliveries.
- If Redis/queue is unavailable the queue is `None`: deliveries stay `pending` until the sweep finds a queue — no API block.
- Settings: `webhook_timeout_seconds`, `webhook_max_tries`, `webhook_retry_backoff_seconds`, `webhook_host_allowlist` (empty = any *public* host, the SSRF guard stays on, strict-security warns when it is empty).
- Critical module: TDD with 100% branch coverage required (auth/voting/flow/budget/webhooks/audit). Whitelist dispatch, never eval. All error paths return `application/problem+json`.

**Related:** be-admin, be-flow, conventions
