---
name: alembic-revision-id-limit
description: Alembic revision ids must be ≤32 chars — alembic_version.version_num is varchar(32)
metadata: 
  node_type: memory
  type: feedback
---

**Alembic revision ids in this repo MUST be ≤32 characters.** The `alembic_version.version_num`
column is `varchar(32)`. A longer `revision: str = "..."` value passes locally, because the
alembic offline `heads` command does not write the column. The same value then **fails the deploy
migration** on the `UPDATE alembic_version` step with
`StringDataRightTruncationError: value too long for type character varying(32)`.

2026-06-13: `0024_expense_payment_method_paypal` (34 characters) broke the deploy. We renamed it
to `0024_expense_paypal` (19 characters). The transactional DDL rolled back cleanly and the
database stayed at 0023. The fix was to rename the revision id and the file, then redeploy.

**How to apply:** when you create a migration, keep the `revision` value and the filename in the
form `00NN_short_slug`, at most 32 characters. Verify with
`grep -rh '^revision: str' backend/migrations/versions/*.py | sed 's/.*= //;s/"//g' | awk '{print length,$0}' | sort -rn | head`.
The longest existing id is `0010_application_email_confirmed`, which is exactly 32 characters.
[[ng-build-budgets]] is the analogous "passes locally, fails the real build" gotcha for the
frontend.
