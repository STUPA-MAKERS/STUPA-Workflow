---
id: "000626"
title: A migrated database has the schema of the models
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/migrations
  - backend/app/models.py
  - backend/tests/integration
  - .github/workflows/ci.yml
---

# A migrated database has the schema of the models

After the upgrade of 000625, CI must compare the schema of the database with `Base.metadata`.
The compare must cover tables, columns, types, nullability, indexes, unique constraints, check
constraints and foreign keys. Each difference must fail the job. An exception must be an entry
in a list in the test, and the entry must give its cause.

Reason: A change to a model without a migration gives a correct fresh database and a wrong
production database. A check constraint that a migration drops by the wrong name stays in
production and refuses a valid write.

Test: The CI job `be-migrations`.
