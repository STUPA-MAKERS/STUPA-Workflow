---
name: be-webhooks
description: Outbound event webhooks — SSRF-guarded, HMAC-SHA256-signed HTTP POST delivery via the arq deliver_webhook worker. Flow actions and domain events fan out over the webhook/webhook_delivery tables. Use when working on webhook dispatch, SSRF guard, signing, retry/dead-letter, or the /api/admin/webhooks CRUD in backend/app/modules/webhooks.
---

# Webhooks (outbound event dispatch) — `backend/app/modules/webhooks`

**Does:** Delivers signed outbound HTTP webhooks for domain events. The module separates dispatch from delivery. Dispatch finds the subscribed webhooks, creates `pending` deliveries and enqueues arq jobs. Delivery runs in the worker. The worker re-resolves DNS and runs the SSRF guard at send-time. It then HMAC-signs the request, POSTs it without redirects, and writes back status, attempts and backoff.

**Key files:**
- `service.py` — `WebhookService`: `dispatch_event`/`dispatch_to_webhook` (API side) + `deliver` (worker side), plus status classification, retry/backoff/dead-letter, `DeliveryOutcome`
- `ssrf.py` — `assert_allowed_url` (scheme/allowlist/resolved-IP check), `pin_url` (DNS-rebind pinning), `_unmap` (unwraps IPv4-mapped/6to4/NAT64), `SsrfError`, injectable `Resolver`
- `signing.py` — HMAC-SHA256 over `"{timestamp}.{body}"`, `canonical_body`, `build_headers`. Header names `X-Signature`/`X-Timestamp`/`X-Webhook-Event`
- `queue.py` — `WebhookQueue` Protocol + `ArqWebhookQueue`. `WEBHOOK_TASK_NAME="deliver_webhook"`, job id `webhook:<delivery_id>` (coalesces duplicate enqueues)
- `action_dispatcher.py` — `WebhookActionDispatcher`: flow-engine `webhook` action handler → `dispatch_to_webhook`. Event `application.transition`
- `worker/webhook.py` (sibling, not in module dir) — arq task `deliver_webhook`. Maps `retry`→`arq.Retry`, no-redirect httpx client
- Models live in `app/modules/admin/models.py`. Schemas live in `app/modules/admin/schemas.py`. The CRUD router lives in `app/modules/admin/router.py`

**Domain / data model:**
- `Webhook` (table `webhook`): `name`, `url`, `events` (Text[] whitelist), `secret` (LargeBinary, server-generated `secrets.token_bytes(32)`, never returned/logged), `active`.
- `WebhookDelivery` (table `webhook_delivery`): `webhook_id` (FK CASCADE), `event`, `payload` (JSONB), `status` ∈ `pending|ok|failed|dead` (CHECK), `attempts`, `idempotency_key`, `last_at`, `next_at`, `response_code`. Index `(status, next_at)` = worker pickup. Unique `(webhook_id, idempotency_key)` = dedup (NULL key = no dedup, migration 0012).
- `events` values are `EventName` from `app/shared/config_schemas.py`: `application_created`, `application_updated`, `status_changed`, `vote_opened`, `vote_closed`, `application_approved`, `application_rejected`, `comment_added`, `budget_reserved`, `budget_booked`, `protocol_finalized`, `deadline_approaching`, `deadline_passed`.

**API surface:** (admin router, permission `webhook.manage`)
- `GET /api/admin/webhooks` — list (`webhook.manage` OR `flow.configure`)
- `POST /api/admin/webhooks` — create (201, secret auto-generated)
- `PATCH /api/admin/webhooks/{webhook_id}` — update
- No DELETE route and no public delivery-status route. No router inside this module — CRUD is in admin.

**Conventions & gotchas:**
- The SSRF guard runs **at send-time in the worker**, not at config time. To defend against DNS rebinding, it resolves **all** A/AAAA records. One non-global record blocks the whole delivery. `_unmap` unwraps IPv4-mapped (`::ffff:`), 6to4 (`2002::/16`) and NAT64 (`64:ff9b::/96`) addresses. An embedded private or metadata IPv4 therefore cannot slip through as a "global" IPv6. After validation, `pin_url` rewrites the host to the validated IP and carries the original `Host`/SNI. That removes the resolve→connect TOCTOU.
- The signature covers `"{timestamp}.{body}"` (Stripe-style). The HMAC includes the timestamp, which gives replay protection. The module **never logs the `secret`**.
- SSRF block = permanent → delivery goes straight to `dead`, **no retry**, and the log line omits host/IP (no internal topology in logs). 4xx → `dead` (non-retryable). 5xx/timeout/transport → `failed`+retry with exponential backoff (`webhook_retry_backoff_seconds * 2^(n-1)`) until `webhook_max_tries`, then `dead`.
- Worker POSTs with `follow_redirects=False` and reads the response body **streamed, capped at 64 KiB** (only the status code matters) to avoid OOM from a hostile receiver.
- Idempotency: dispatch dedups on `(webhook_id, idempotency_key)` via a per-delivery savepoint (`begin_nested`) that catches the unique-violation race. The arq job key `webhook:<delivery_id>` coalesces duplicate enqueues. Flow actions derive the idempotency base from `DispatchedAction.idempotency_key`.
- If Redis/queue is unavailable the queue is `None`: deliveries stay `pending`, callers log and skip — no API block.
- Settings: `webhook_timeout_seconds`, `webhook_max_tries`, `webhook_retry_backoff_seconds`, `webhook_host_allowlist` (empty = any *public* host, the SSRF guard stays on, strict-security warns when it is empty). See `[[security-audit-2026-06-13]]`.
- Critical module: TDD with 100% branch coverage required (auth/voting/flow/budget/webhooks/audit). Whitelist dispatch, never eval. All error paths return `application/problem+json`.

**Related:** be-admin, be-flow, conventions
