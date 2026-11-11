---
id: "000625"
title: CI runs the new migrations on the schema of the last release
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - .github/workflows/ci.yml
  - backend/migrations/README.md
scope:
  - backend/migrations
  - backend/tests/integration
  - .github/workflows/ci.yml
---

# CI runs the new migrations on the schema of the last release

CI must build a database with the schema of the newest release tag. To do this, it must run
`alembic upgrade head` from the code of that tag. Then CI must run `alembic upgrade head` from
the code of the pull request on this database. An error in this second run must fail the job.
The job must run for every pull request and must not be opt-in.

Reason: The baseline builds a fresh database from the models of the same commit. On a fresh
database, a later migration finds its tables and columns in place and changes nothing. Only a
database with an older schema runs the `ALTER` statements that production runs.

Test: The CI job `be-migrations`.
