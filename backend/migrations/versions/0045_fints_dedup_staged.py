"""fints_dedup_staged: resolve re-imported duplicates of staged rows from the RAW DATA.

Before the raw-data idempotency key (#fints-raw), parser-derived fields fed the hash
(``counterparty_iban`` and the normalized purpose). A parser improvement moved that hash,
so a new fetch created the same bank transaction a second time. The typical result is a
booked ``matched`` row plus a freshly parsed ``unmatched`` duplicate.

This migration compares over ``raw_dedup_base`` only: value date, amount, E2E, canonical
raw purpose and canonical raw counterparty block. All of these come from ``raw_payload``
and never depend on the parser. Rows with the same raw base are the same transaction. The
**booked** row survives, otherwise the oldest row survives. The booking itself stays
untouched, because the display resolves live from the raw data. The migration deletes the
unbooked copies. A group without a booked row AND without a true raw duplicate stays
untouched. Five real payments of 80 EUR on the same day carry different raw originators,
so they do NOT collapse. The surviving row gets the new raw key. The down migration does
nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0045_fints_dedup_staged"
down_revision: str | None = "0044_fints_purpose_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Call the shared idempotent routine, so one logic serves 0045 and 0046. The logic
    # stays out of this file on purpose. Earlier versions of this revision already ran,
    # so alembic skips them. Revision 0046 calls the same function to apply the fix.
    from app.modules.budget.bank.maintenance import dedup_staged_lines

    dedup_staged_lines(op.get_bind())


def downgrade() -> None:
    pass
