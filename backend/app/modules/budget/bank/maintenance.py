"""One-off cleanup routines for staged bank statement lines.

These routines stay separate from the service, which uses the async ORM. A
migration works with a synchronous ``Connection`` (``op.get_bind()``). The fixes
are pure and idempotent. Migrations 0045 and 0046 call them, so the logic exists
once and no migration script repeats it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


def dedup_staged_lines(conn: Connection) -> int:
    """Collapse re-imported duplicates of staged lines, comparing only raw data.

    The function groups the lines per account and identical raw base. It keeps a
    matched line, or the oldest line when the group holds no matched line. It then
    deletes the remaining unbooked exact duplicates. The keeper gets the new raw
    key, so the next fetch recognizes it. The function never deletes a matched
    line. A group without duplicates stays untouched. The function is idempotent.

    Returns:
        The number of deleted lines.
    """
    from app.modules.budget.bank.dedup import raw_dedup_base, sha256_hex

    rows = conn.execute(
        text(
            "SELECT l.id, l.account_id, l.value_date, l.amount, l.end_to_end_id, "
            "l.match_state, l.created_at, l.raw_payload, a.iban AS acc_iban "
            "FROM bank_statement_line l JOIN account a ON a.id = l.account_id "
            "ORDER BY l.account_id, l.created_at"
        )
    ).all()

    groups: dict[tuple[object, ...], list] = {}
    for r in rows:
        base = raw_dedup_base(r.value_date, r.amount, r.end_to_end_id, r.raw_payload)
        groups.setdefault((r.account_id, *base), []).append(r)

    deleted = 0
    for key, grp in groups.items():
        if len(grp) < 2:
            continue
        non_matched = [g for g in grp if g.match_state != "matched"]
        if not non_matched:
            continue  # only matched lines (no re-import): leave untouched
        matched = [g for g in grp if g.match_state == "matched"]
        keeper = matched[0] if matched else non_matched[0]
        for g in non_matched:
            if g.id == keeper.id:
                continue
            conn.execute(
                text("DELETE FROM bank_statement_line WHERE id = :id"), {"id": g.id}
            )
            deleted += 1
        scope = keeper.acc_iban or str(keeper.account_id)
        new_key = sha256_hex(f"{scope}|{'|'.join(str(p) for p in key[1:])}|0")
        conn.execute(
            text("UPDATE bank_statement_line SET idempotency_key = :k WHERE id = :id"),
            {"k": new_key, "id": keeper.id},
        )
    return deleted
