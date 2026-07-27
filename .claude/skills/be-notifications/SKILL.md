---
name: be-notifications
description: Email notifications backend — Jinja2 SandboxedEnvironment mail templates (i18n DE/EN, builtin catalog + DB overrides), per-user opt-out preferences (NOTIFICATION_KINDS), recipient resolution (group/role/gremium/applicant/email/permission). Also branded HTML layout, arq enqueue + idempotency keys, flow notify/task dispatch, comment/role/delegation/meeting/privacy auto-mails, magic-link. Use when working on mail templates, notification rules, recipients, preferences, /api/notifications, /api/admin/mail-templates, or send_mail dispatch in backend/app/modules/notifications.
---

# Notifications (mail) — `backend/app/modules/notifications`

**Does:** Renders i18n mail templates (Jinja2 sandbox, DE/EN) into branded HTML/text and enqueues them to an arq worker for async SMTP delivery. It drives every platform email — flow status/task notices, comment/role/delegation/meeting/privacy auto-mails, task reminders, magic-link — with per-user opt-out preferences, recipient resolution, and idempotent de-duplication.

**Key files:**
- `service.py` — `NotificationService`: template CRUD + preview, preferences merge/upsert, `handle_notify_action` (flow `notify`), `send_kind_mail` (generic), `send_magic_link`, `filter_recipients_by_preference`. `_enqueue` drops silently when the queue is None (no Redis).
- `templating.py` — pure render on `*_i18n` dicts via `SandboxedEnvironment` + `StrictUndefined`. It strips CR/LF from the subject (header-injection guard) and raises `TemplateRenderError`. `_env` (text, no autoescape) / `_env_html` (autoescape).
- `templates_catalogue.py` — `TEMPLATE_CATALOGUE` / `CATALOGUE_BY_KEY`: single source listing every mail key + builtin subject/body (imported from the sending modules) + placeholder docs. This file defines the `task_reminder` and `deadline_approaching` builtins.
- `kinds.py` — `NOTIFICATION_KINDS` tuple, the opt-outable categories. magic_link is NOT in it, so a user cannot switch it off.
- `recipients.py` — `RecipientResolver.resolve(specs)` → emails. Also `actionable_principal_emails` / `state_actionable` (task semantics #64).
- `events.py` — `EVENTS` whitelist tuple + `is_event` (webhook event source of truth, NOT mail).
- `mail.py` — `MailMessage`/`MailAttachment` value objects (queue-serializable), `compute_idempotency_key` (sha256 → `mail:<digest>`), `MailSender` protocol, `Capturing`/`Smtp` senders, `build_email_message`.
- `queue.py` — `MailQueue` protocol. `ArqMailQueue` (enqueues the `send_mail` job, `_job_id = idempotency_key` → dedup) or `DirectMailQueue` (inline, tests).
- `provider.py` — best-effort arq pool lifecycle. `mail_queue_from_pool` returns None when there is no Redis.
- `layout.py` — `render_layout` branded HTML wrapper + per-kind footer reason text + `text_to_html`/`_linkify`.
- `action_dispatcher.py` — `NotificationActionDispatcher` implements the flow `ActionDispatcher`. It handles `notify` + `taskNotify` and logs other action types.
- `auto.py` — `AutoMailer` background best-effort mails: meeting created, role assigned/revoked, delegation granted/revoked.
- `comments.py` — `send_comment_notifications` (applicant↔team, #4-1).
- `privacy.py` — GDPR erasure mails (requested/executed/rejected).
- `models.py` — SQLAlchemy tables. `router.py`/`schemas.py` — API + camelCase DTOs.

**Domain / data model:**
- `mail_template` (`MailTemplate`): `key` (unique), `subject_i18n`/`body_i18n`/`body_html_i18n`/`placeholders` (all JSONB). A DB row is an *override* of a catalog *builtin*. `MailTemplateOut.source` ∈ `override`|`builtin`. Builtins have `id=None`.
- `notification_preference` (`NotificationPreference`): PK `(principal_id, kind)`, `enabled`. Opt-out store: the table holds only deviations from the all-enabled default. `kind ∈ NOTIFICATION_KINDS`.
- `notification_settings` (`NotificationSettings`): single row (`CheckConstraint id=1`), `task_reminder_enabled`, `task_reminder_after_days` (≥1), `task_reminder_repeat_days` (≥0, 0=once per state stay).
- `task_reminder_log` (`TaskReminderLog`): PK `application_id`, `status_event_id` (binds the reminder to a state stay, a state change restarts the count), `reminded_at`.
- `NOTIFICATION_KINDS`: status_update, comment, task, task_reminder, meeting, vote, role_change, delegation, protocol, deadline, privacy.
- Recipient spec kinds: `group` (oidc_groups), `role` (active RoleAssignment), `gremium` (active members), `applicant` (non-anonymized applicant email), `email` (literal), `permission` (holders of a permission, admin role always counts).
- Mail template keys (catalog): status_update, task_new, task_reminder, deadline_approaching, comment_applicant, comment_team, meeting_created, role_assigned, role_revoked, delegation_granted, delegation_revoked, magic_link, erasure_requested, erasure_executed, erasure_rejected.

**API surface:**
- `GET /api/notifications/preferences` — own effective switches (full catalog, default on). Any logged-in principal.
- `PUT /api/notifications/preferences` — bulk-set own switches (only deviations stored, unknown kinds → 422).
- `GET /api/admin/notification-settings` — read the platform task-reminder config. Perm `admin.notifications`.
- `PUT /api/admin/notification-settings` — partial update, audited as `CONFIG_CHANGE`. Perm `admin.notifications`.
- `GET /api/admin/mail-templates` — list every mail (override or builtin). Perm `admin.notifications`.
- `POST /api/admin/mail-templates` — create (409 on dup key).
- `PATCH /api/admin/mail-templates/{id}` — partial update (key immutable).
- `PUT /api/admin/mail-templates` — upsert override by key (builtin keys allowed, unknown key → 422).
- `DELETE /api/admin/mail-templates/by-key/{key}` — reset override → restore builtin.
- `POST /api/admin/mail-templates/preview` — render an editor draft (no persisted id).
- `POST /api/admin/mail-templates/{id}/preview` — render stored template with sample context + lang.

**Conventions & gotchas:**
- **Sandbox always.** Templates render in `SandboxedEnvironment` with `StrictUndefined`. An unknown placeholder raises loudly and the preview shows the error. There is no eval and no attribute escape, even though admins author the templates. Never swap in a plain Jinja `Environment`. Subjects pass `_sanitize_subject` (CR/LF removed) — keep that for any new subject path.
- **Never send synchronously.** The service only *enqueues*. The arq worker `send_mail` (`worker/mail.py`, task name `MAIL_TASK_NAME = "send_mail"`) rebuilds `MailMessage.from_payload` and sends through `SmtpMailSender`. If the queue is None (no Redis), the service logs the mail and drops it. The API returns normally and never blocks (202-style).
- **Idempotency.** `compute_idempotency_key(*parts)` becomes the arq `_job_id`, so identical enqueues coalesce. Always pass stable `idempotency_parts` (event/app/template) so a worker retry does not send twice.
- **The catalog is the single source.** Each builtin lives in its sending module, and `templates_catalogue.py` re-exports it. The editor and the send-fallback share the *same* objects (no DB seeding). To add a mail, do three steps. Add the builtin in the sender. Register a `MailTemplateSpec` in `TEMPLATE_CATALOGUE`. If the mail is opt-outable, add a `kind` to `NOTIFICATION_KINDS` and a footer reason in `layout._REASONS`. Edit DE **and** EN.
- **Preference filtering is fail-open** for unknown kinds. It matches on the principal email (CITEXT, case-insensitive). It never filters an address without an account (anonymous applicants, lists). `magic_link` is intentionally NOT in `NOTIFICATION_KINDS` because it is essential.
- **Auto-mails are best-effort background tasks** (`auto.py`, `comments.py`, `privacy.py`). Each one opens its own sessionmaker *after* the triggering commit. It logs and swallows any exception, because a mail failure must never break the request.
- **Status and task mails for a status change run as flow actions**, NOT in `auto.py`. Implicit notifications go to `NotificationActionDispatcher` (`notify`/`taskNotify`). `notify` without an explicit `templateKey` falls back to `status_update`. The context auto-fills an empty `applicationTitle`/`status`, so `StrictUndefined` does not kill delivery.
- **Logs carry no PII** (`mail.py`): only recipient domains + idempotency key — never addresses, subject, body, or SMTP password.
- `events.EVENTS` is the **webhook** event whitelist, not the mail catalog — do not conflate it with `kinds`/template keys.
- `router.py` exposes three routers (`router`, `admin_router`, `templates_router`). `main.py` includes each one separately.

**Related:** be-flow, be-webhooks, be-auth, be-admin, be-applications, be-livevote, be-delegations, be-audit
