---
id: "000089"
title: The exceptions are named
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - mcp/
  - typst/typst_service/
---

# The exceptions are named

The rules 000081 to 000088 must not apply to these parts:

- SQLAlchemy ORM rows and Alembic migrations
- tests
- `try`, `with` and `raise`
- Pydantic validators and framework wiring
- Angular signals in event handlers
- ngx-formly field configs and Reactive Forms
- DOM APIs and RxJS subscriptions

Reason: The library or the language needs them in this form.
