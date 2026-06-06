"""Notifications-Modul (T-18): Regeln, Mail-Templates (Jinja2/i18n), Versand.

Öffentliche Bausteine:

* :mod:`events`     — stabile Event-Liste (api.md §6).
* :mod:`mail`       — `MailMessage` + `MailSender`-Protokoll (SMTP/Capturing).
* :mod:`templating` — Jinja2-Render (Subject/Body, i18n DE/EN, Vorschau).
* :mod:`queue`      — Enqueue-Abstraktion (arq) + idempotenter Job-Key.
* :mod:`service`    — Regel-/Template-CRUD, Event-Dispatch, `notify`-Action-Handler.
* :mod:`router`     — `/api/admin/notification-rules` + `/mail-templates` (+ Vorschau).
"""
