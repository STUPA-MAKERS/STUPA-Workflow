---
id: "000089"
title: The exceptions are named
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
---

# The exceptions are named

These stay mutable or imperative: SQLAlchemy ORM rows, Alembic migrations, tests, `try`,
`with` and `raise`, Pydantic validators, framework wiring, Angular signals in event handlers,
ngx-formly field configs and Reactive Forms, DOM APIs, RxJS subscriptions.

Reason: The library or the language needs them in this form.
