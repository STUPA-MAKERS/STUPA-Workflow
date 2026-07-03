"""Notifications module: rules, mail templates (Jinja2/i18n), dispatch.

Public building blocks:

* :mod:`events`     — stable event list.
* :mod:`mail`       — ``MailMessage`` + ``MailSender`` protocol (SMTP/capturing).
* :mod:`templating` — Jinja2 rendering (subject/body, i18n DE/EN, preview).
* :mod:`queue`      — enqueue abstraction (arq) + idempotent job key.
* :mod:`service`    — rule/template CRUD, event dispatch, ``notify`` action handler.
* :mod:`router`     — ``/api/admin/notification-rules`` + ``/mail-templates`` (+ preview).
"""
