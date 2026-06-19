---
name: be-notifications
description: Email notifications backend — Jinja2 SandboxedEnvironment mail templates (i18n DE/EN, builtin catalogue + DB overrides), per-user opt-out preferences (NOTIFICATION_KINDS), recipient resolution (group/role/gremium/applicant/email/permission), branded HTML layout, arq enqueue + idempotency keys, flow notify/task dispatch, comment/role/delegation/meeting/privacy auto-mails, magic-link. Use when working on mail templates, notification rules, recipients, preferences, /api/notifications, /api/admin/mail-templates, or send_mail dispatch in backend/app/modules/notifications.
---

# Notifications (mail) — `backend/app/modules/notifications`

**Does:** Renders i18n mail templates (Jinja2 sandbox, DE/EN) into branded HTML/text and enqueues them to an arq worker for async SMTP delivery. Drives every platform email — flow status/task notices, comment/role/delegation/meeting/privacy auto-mails, task reminders, magic-link — with per-user opt-out preferences, recipient resolution, and idempotent de-duplication.

**Key files:**
- `service.py` — `NotificationService`: template CRUD + preview, preferences merge/upsert, `handle_notify_action` (flow `notify`), `send_kind_mail` (generic), `send_magic_link`, `filter_recipients_by_preference`; `_enqueue` drops silently if queue is None (no Redis).
- `templating.py` — pure render on `*_i18n` dicts via `SandboxedEnvironment` + `StrictUndefined`; subject CR/LF stripped (header-injection guard); raises `TemplateRenderError`. `_env` (text, no autoescape) / `_env_html` (autoescape).
- `templates_catalogue.py` — `TEMPLATE_CATALOGUE` / `CATALOGUE_BY_KEY`: single source listing every mail key + builtin subject/body (imported from the sending modules) + placeholder docs; `task_reminder` & `deadline_approaching` builtins defined here.
- `kinds.py` — `NOTIFICATION_KINDS` tuple (the opt-outable categories; magic_link is NOT here = unstoppable).
- `recipients.py` — `RecipientResolver.resolve(specs)` → emails; `actionable_principal_emails` / `state_actionable` (task semantics #64).
- `events.py` — `EVENTS` whitelist tuple + `is_event` (webhook event source of truth, NOT mail).
- `mail.py` — `MailMessage`/`MailAttachment` value objects (queue-serializable), `compute_idempotency_key` (sha256 → `mail:<digest>`), `MailSender` protocol, `Capturing`/`Smtp` senders, `build_email_message`.
- `queue.py` — `MailQueue` protocol; `ArqMailQueue` (enqueues `send_mail` job, `_job_id = idempotency_key` → dedup) / `DirectMailQueue` (inline, tests).
- `provider.py` — best-effort arq pool lifecycle; `mail_queue_from_pool` (None if no Redis).
- `layout.py` — `render_layout` branded HTML wrapper + per-kind footer reason text + `text_to_html`/`_linkify`.
- `action_dispatcher.py` — `NotificationActionDispatcher` implements flow `ActionDispatcher`; handles `notify` + `taskNotify`, logs other action types.
- `auto.py` — `AutoMailer` background best-effort mails: meeting created, role assigned/revoked, delegation granted/revoked.
- `comments.py` — `send_comment_notifications` (applicant↔team, #4-1).
- `privacy.py` — GDPR erasure mails (requested/executed/rejected).
- `models.py` — SQLAlchemy tables. `router.py`/`schemas.py` — API + camelCase DTOs.

**Domain / data model:**
- `mail_template` (`MailTemplate`): `key` (unique), `subject_i18n`/`body_i18n`/`body_html_i18n`/`placeholders` (all JSONB). A DB row is an *override* of a catalogue *builtin*; `MailTemplateOut.source` ∈ `override`|`builtin`; builtins have `id=None`.
- `notification_preference` (`NotificationPreference`): PK `(principal_id, kind)`, `enabled`. Opt-out store — only deviations from the all-enabled default are persisted; `kind ∈ NOTIFICATION_KINDS`.
- `notification_settings` (`NotificationSettings`): single row (`CheckConstraint id=1`), `task_reminder_enabled`, `task_reminder_after_days` (≥1), `task_reminder_repeat_days` (≥0, 0=once per state stay).
- `task_reminder_log` (`TaskReminderLog`): PK `application_id`, `status_event_id` (binds reminder to a state stay; state change → recount), `reminded_at`.
- `NOTIFICATION_KINDS`: status_update, comment, task, task_reminder, meeting, vote, role_change, delegation, protocol, deadline, privacy.
- Recipient spec kinds: `group` (oidc_groups), `role` (active RoleAssignment), `gremium` (active members), `applicant` (non-anonymized applicant email), `email` (literal), `permission` (holders of a permission, admin role always counts).
- Mail template keys (catalogue): status_update, task_new, task_reminder, deadline_approaching, comment_applicant, comment_team, meeting_created, role_assigned, role_revoked, delegation_granted, delegation_revoked, magic_link, erasure_requested, erasure_executed, erasure_rejected.

**API surface:**
- `GET /api/notifications/preferences` — own effective switches (full catalogue, default on); any logged-in principal.
- `PUT /api/notifications/preferences` — bulk-set own switches (only deviations stored; unknown kinds → 422).
- `GET /api/admin/notification-settings` — read platform task-reminder config; P `admin.notifications`.
- `PUT /api/admin/notification-settings` — partial update, audited as `CONFIG_CHANGE`; P `admin.notifications`.
- `GET /api/admin/mail-templates` — list every mail (override-or-builtin); P `admin.notifications`.
- `POST /api/admin/mail-templates` — create (409 on dup key).
- `PATCH /api/admin/mail-templates/{id}` — partial update (key immutable).
- `PUT /api/admin/mail-templates` — upsert override by key (builtin keys allowed; unknown key → 422).
- `DELETE /api/admin/mail-templates/by-key/{key}` — reset override → restore builtin.
- `POST /api/admin/mail-templates/preview` — render an editor draft (no persisted id).
- `POST /api/admin/mail-templates/{id}/preview` — render stored template with sample context + lang.

**Conventions & gotchas:**
- **Sandbox always.** Templates render in `SandboxedEnvironment` with `StrictUndefined` — unknown placeholders raise loudly (preview shows it) and no eval/attribute escape, even though admins author templates. Never swap in a plain Jinja `Environment`. Subjects pass `_sanitize_subject` (CR/LF removed) — keep that for any new subject path.
- **Never send synchronously.** The service only *enqueues*; the arq worker `send_mail` (`worker/mail.py`, task name `MAIL_TASK_NAME = "send_mail"`) reconstructs `MailMessage.from_payload` and sends via `SmtpMailSender`. If the queue is None (no Redis), the mail is logged + dropped — API returns normally, never blocks (202-style).
- **Idempotency.** `compute_idempotency_key(*parts)` → arq `_job_id`; identical enqueues coalesce. Always pass stable `idempotency_parts` (event/app/template) so worker retries don't double-send.
- **Catalogue is the single source.** Builtins live in their sending module and are re-exported into `templates_catalogue.py`; the editor and the send-fallback share the *same* objects (no DB seeding). To add a mail: add the builtin in the sender, register a `MailTemplateSpec` in `TEMPLATE_CATALOGUE`, and (if opt-outable) add a `kind` to `NOTIFICATION_KINDS` + a footer reason in `layout._REASONS`. Edit DE **and** EN.
- **Preference filtering is fail-open** for unknown kinds; matches on principal email (CITEXT, case-insensitive); addresses without an account (anonymous applicants, lists) are never filtered. `magic_link` is intentionally NOT in `NOTIFICATION_KINDS` (essential).
- **Auto-mails are best-effort background tasks** (`auto.py`, `comments.py`, `privacy.py`): each opens its own sessionmaker *after* the triggering commit; any exception is logged and swallowed — a mail failure must never break the request.
- **Status/task mails per status change run as flow actions**, NOT in `auto.py`: implicit notifications → `NotificationActionDispatcher` (`notify`/`taskNotify`). `notify` without an explicit `templateKey` defaults to `status_update`; context auto-fills empty `applicationTitle`/`status` so `StrictUndefined` doesn't kill delivery.
- **Logs carry no PII** (`mail.py`): only recipient domains + idempotency key — never addresses, subject, body, or SMTP password.
- `events.EVENTS` is the **webhook** event whitelist, not the mail catalogue — don't conflate it with `kinds`/template keys.
- `router.py` exposes three routers (`router`, `admin_router`, `templates_router`) included separately in `main.py`.

**Related:** be-flow, be-webhooks, be-auth, be-admin, be-applications, be-livevote, be-delegations, be-audit
