"""Notifications module: rules, mail templates (Jinja2 and i18n), dispatch.

Public building blocks:

`events`: the stable event list.
`mail`: `MailMessage` and the `MailSender` protocol (SMTP or capturing).
`templating`: Jinja2 rendering of subject and body, i18n DE and EN, preview.
`queue`: the enqueue abstraction (arq) and the idempotent job key.
`service`: rule and template CRUD, event dispatch, the `notify` action handler.
`router`: `/api/admin/notification-rules` and `/mail-templates`, with preview.
"""
