---
name: alembic-revision-id-limit
description: Alembic revision ids must be ≤32 chars — alembic_version.version_num is varchar(32)
metadata: 
  node_type: memory
  type: feedback
---

**Alembic revision ids in this repo MUST be ≤32 characters.** The `alembic_version.version_num` column is `varchar(32)`. A longer `revision: str = "..."` passes locally (alembic offline `heads` doesn't write the column) but **fails the deploy migration** with `StringDataRightTruncationError: value too long for type character varying(32)` on the `UPDATE alembic_version` step.

2026-06-13: `0024_expense_payment_method_paypal` (34) broke the deploy; renamed to `0024_expense_paypal` (19). Transactional DDL rolled back cleanly (DB stayed at 0023), so the fix was just renaming the revision id + file and redeploying.

**How to apply:** when creating a migration, keep `revision`/filename like `00NN_short_slug`, ≤32 chars. Verify: `grep -rh '^revision: str' backend/migrations/versions/*.py | sed 's/.*= //;s/"//g' | awk '{print length,$0}' | sort -rn | head`. The longest existing is `0010_application_email_confirmed` (exactly 32). [[ng-build-budgets]] is the analogous "passes locally, fails the real build" gotcha for the frontend.
