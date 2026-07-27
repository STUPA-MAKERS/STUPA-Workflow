"""Map CAMT.052/053 statements (XML) to `statement.StatementLine`.

The parser is namespace-tolerant (it matches the local name) and version-tolerant (any
`camt.05x.001.yy`). It splits a batch booking (one `Ntry` with several `TxDtls`) into
single transactions. Each `TxDtls` becomes one line with its own amount, purpose and
counterparty. The split runs only when the partial amounts add up exactly to the entry
amount. If they do not, the parser keeps one line with the total.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.modules.budget.bank.normalize import (
    clean,
    skip_notprovided,
    split_booking_time,
    split_leading_iban,
)
from app.modules.budget.bank.statement import (
    StatementBalance,
    StatementLine,
    StatementParseError,
    sane_amount,
)


def parse_camt(
    data: bytes,
    iban: str | None = None,
    account_ids: Collection[str] | None = None,
) -> list[StatementLine]:
    """Parse a CAMT statement (report `camt.052` or statement `camt.053`).

    One HKCAZ fetch can return a COMBINED `camt.053` with one `<Stmt>` per account of
    the login. Without a scope, the parser merges the bookings of every account and
    stages them under the one selected account. The parser therefore skips a statement
    that identifies a DIFFERENT account, by IBAN or by proprietary account number. It
    keeps a statement without an identifiable account, and it keeps everything when the
    scope is empty (file imports). This fallback keeps existing file imports working.

    `iban` scopes the result to one account. `account_ids` scopes it by account number.
    Use `account_ids` when the bank exposes no IBAN, as older Sparkasse SEPA accounts do.

    Raises:
        StatementParseError: The CAMT XML is missing or broken, or it holds no usable
            entries.
    """
    try:
        root = ET.fromstring(data)  # noqa: S314 - own statement, no external entities
    except ET.ParseError as exc:
        raise StatementParseError(f"unparseable CAMT XML: {exc}") from exc

    want = {n for n in (_norm_id(x) for x in _scope_values(iban, account_ids)) if n}
    entries = _scoped_entries(root, want)
    if not entries:
        raise StatementParseError("CAMT XML contained no entries (Ntry)")

    lines: list[StatementLine] = []
    for ntry in entries:
        lines.extend(_lines_from_entry(ntry))
    if not lines:
        raise StatementParseError("CAMT XML contained no usable entries")
    return lines


def _scope_values(iban: str | None, account_ids: Collection[str] | None) -> list[str]:
    return [iban or "", *(account_ids or ())]


def _norm_id(value: str | None) -> str:
    """Normalize an account identifier (IBAN or number) for comparison."""
    return (value or "").replace(" ", "").upper()


def statement_account_ids(data: bytes) -> list[str]:
    """Return the account identifiers (IBAN or number) of every statement in a CAMT doc.

    This diagnostic helper shows which accounts a fetched document carries. It tells an
    all-accounts fetch apart from an empty scope. Broken XML gives an empty list.
    """
    try:
        root = ET.fromstring(data)  # noqa: S314 - own statement, no external entities
    except ET.ParseError:
        return []
    ids: list[str] = []
    for stmt in _findall_local(root, "Stmt") + _findall_local(root, "Rpt"):
        ids.extend(sorted(_stmt_account_ids(stmt)))
    return ids


def _stmt_account_ids(stmt: ET.Element) -> set[str]:
    """Return the identifiers of the OWN account of a statement.

    The identifiers are the IBAN and the proprietary account number
    (`<Acct>/<Id>/<Othr>/<Id>`). The result is empty when the account is not
    identifiable. The statement account is the first `<Acct>` in document order.
    Counterparty accounts are `<DbtrAcct>` and `<CdtrAcct>`, not `<Acct>`.
    """
    acct = _find_local(stmt, "Acct")
    if acct is None:
        return set()
    ids = {_norm_id(_find_text_local(acct, "IBAN"))}
    # Compare the proprietary account number with the leading zeros stripped. Banks pad
    # it inconsistently between the account list and the statement.
    ids.add(_norm_id(_find_text_local(_find_local(acct, "Othr"), "Id")).lstrip("0"))
    return {i for i in ids if i}


def _scoped_entries(root: ET.Element, want: set[str]) -> list[ET.Element]:
    """Return the `Ntry` elements of the statements that match `want`.

    In camt.053 the bookings sit under one `<Stmt>` per account. In camt.052 they sit
    under `<Rpt>`. Drop a statement only when it identifies a DIFFERENT account. Never
    drop it when the account is not identifiable, or when `want` is empty. That rule
    avoids an empty fetch when a bank omits the identifier or varies it. A document
    without any statement container falls back to a flat `Ntry` scan.
    """
    statements = _findall_local(root, "Stmt") + _findall_local(root, "Rpt")
    if not statements:
        return _findall_local(root, "Ntry")
    entries: list[ET.Element] = []
    for stmt in statements:
        if want:
            ids = _stmt_account_ids(stmt)
            if ids and ids.isdisjoint(want):
                continue
        entries.extend(_findall_local(stmt, "Ntry"))
    return entries


@dataclass(slots=True)
class _Entry:
    """Facts read once from an `Ntry` and shared by every line derived from it."""

    amount: Decimal  # signed, the reversal flip included
    orig_credit: bool  # the CdtDbtInd of the entry (original direction)
    reversal: bool
    currency: str
    booking_date: date | None
    value_date: date | None
    bank_ref: str | None


def _entry_facts(ntry: ET.Element) -> _Entry | None:
    """Read the amount, direction, reversal flag and dates of one `Ntry`.

    Returns:
        The facts of the entry, or `None` when the entry is unusable.
    """
    amt_el = _find_local(ntry, "Amt")
    if amt_el is None or not (amt_el.text or "").strip():
        return None
    try:
        magnitude = Decimal((amt_el.text or "").strip())
    except (InvalidOperation, ValueError):
        return None
    # Require the direction explicitly. Without a clear CRDT or DBIT the economic
    # direction is unknown. Do not assume an outflow.
    ind = (_find_text_local(ntry, "CdtDbtInd") or "").upper()
    if ind.startswith("CRDT"):
        orig_credit = True
    elif ind.startswith("DBIT"):
        orig_credit = False
    else:
        return None
    # A reversal (`RvslInd=true`) flips the economic direction (chargeback).
    reversal = (_find_text_local(ntry, "RvslInd") or "").strip().lower() in ("true", "1")
    credit = (not orig_credit) if reversal else orig_credit
    # The CAMT `<Amt>` value is >= 0 per spec. A negative value would flip the sign
    # again below. Decouple the amount as a defense. The direction comes from the
    # indicator only.
    amount = sane_amount(abs(magnitude) if credit else -abs(magnitude))
    return _Entry(
        amount=amount,
        orig_credit=orig_credit,
        reversal=reversal,
        currency=(amt_el.get("Ccy") or "EUR").upper(),
        booking_date=_camt_date(_find_local(ntry, "BookgDt")),
        value_date=_camt_date(_find_local(ntry, "ValDt")),
        bank_ref=clean(_find_text_local(ntry, "AcctSvcrRef")),
    )


def _lines_from_entry(ntry: ET.Element) -> list[StatementLine]:
    """Map one `Ntry` to one line (single booking) or n lines (split batch booking)."""
    entry = _entry_facts(ntry)
    if entry is None:
        return []
    tx_details = _findall_local(ntry, "TxDtls")
    if len(tx_details) >= 2:
        split = _split_batch(ntry, entry, tx_details)
        if split is not None:
            return split
    scope = tx_details[0] if tx_details else ntry
    return [_line_from_scope(scope, ntry, entry, amount=entry.amount, bank_ref=entry.bank_ref)]


def _split_batch(
    ntry: ET.Element, entry: _Entry, tx_details: list[ET.Element]
) -> list[StatementLine] | None:
    """Resolve a batch booking into single transactions.

    A split is safe only when every `TxDtls` carries its own `TxAmt` in the entry
    currency. The signed partial amounts must also sum exactly to the entry amount.
    Otherwise the split would invent amounts, for example on a gross or net deviation
    from fees.

    Returns:
        One line per `TxDtls`, or `None` when the split is not safe.
    """
    lines: list[StatementLine] = []
    total = Decimal("0")
    for tx in tx_details:
        amount = _tx_amount(tx, entry)
        if amount is None:
            return None
        # Bank reference per sub-transaction, if there is one. The entry reference is
        # identical for all parts and must NOT be used. All sub-lines would collapse
        # onto the same idempotency key.
        tx_ref = clean(_find_text_local(_find_local(tx, "Refs"), "AcctSvcrRef"))
        lines.append(_line_from_scope(tx, ntry, entry, amount=amount, bank_ref=tx_ref))
        total += amount
    if total != entry.amount:
        return None
    # The split loses the AddtlNtryInf of the entry, for example
    # "SAMMELUEBERWEISUNG DATEI-NR. … ANZAHL …", because each line carries its own
    # Ustrd purpose. Keep it as metadata so staging can match the old total line by
    # its file number.
    info = clean(_find_text_local(ntry, "AddtlNtryInf"))
    batch_meta = {
        "batch": "true",
        "batch_count": str(len(tx_details)),
        "batch_total": str(entry.amount),
        **({"batch_ref": entry.bank_ref} if entry.bank_ref else {}),
        **({"batch_info": info} if info else {}),
    }
    for line in lines:
        line.raw.update(batch_meta)
    return lines


def _tx_amount(tx: ET.Element, entry: _Entry) -> Decimal | None:
    """Return the signed amount of a sub-transaction (`AmtDtls/TxAmt/Amt`).

    The direction comes from the `CdtDbtInd` of the sub-transaction, else from the one
    of the entry. An entry reversal flips it, as it does for the unsplit entry.

    Returns:
        The signed amount, or `None` when the amount or the currency is missing, or
        when the currency does not match the entry currency.
    """
    tx_amt = _find_local(tx, "TxAmt")
    amt_el = _find_local(tx_amt, "Amt") if tx_amt is not None else None
    if amt_el is None or not (amt_el.text or "").strip():
        return None
    if (amt_el.get("Ccy") or entry.currency).upper() != entry.currency:
        return None
    try:
        magnitude = Decimal((amt_el.text or "").strip())
    except (InvalidOperation, ValueError):
        return None
    ind = (_find_text_local(tx, "CdtDbtInd") or "").upper()
    if ind.startswith("CRDT"):
        orig_credit = True
    elif ind.startswith("DBIT"):
        orig_credit = False
    else:
        orig_credit = entry.orig_credit
    credit = (not orig_credit) if entry.reversal else orig_credit
    return sane_amount(abs(magnitude) if credit else -abs(magnitude))


def _line_from_scope(
    scope: ET.Element,
    ntry: ET.Element,
    entry: _Entry,
    *,
    amount: Decimal,
    bank_ref: str | None,
) -> StatementLine:
    """Build one line from a detail scope (`TxDtls` or the `Ntry` itself)."""
    credit = amount > 0
    # The counterparty follows the ORIGINAL direction. Dbtr and Cdtr in the XML refer
    # to it. On a credit this is the debtor (the payer), otherwise the creditor.
    orig_credit = (not credit) if entry.reversal else credit
    party_tag, acct_tag = ("Dbtr", "DbtrAcct") if orig_credit else ("Cdtr", "CdtrAcct")
    party = _find_local(scope, party_tag)
    acct = _find_local(scope, acct_tag)
    cp_name, cp_iban = split_leading_iban(
        _find_text_local(party, "Nm") if party is not None else None,
        _find_text_local(acct, "IBAN") if acct is not None else None,
    )
    purpose, booking_time = split_booking_time(_purpose_text(scope, ntry))
    raw = {
        "creditDebit": "CRDT" if entry.orig_credit else "DBIT",
        **({"reversal": "true"} if entry.reversal else {}),
        **({"booking_time": booking_time} if booking_time else {}),
        # Record the raw purpose. It feeds `resolve_purpose` and makes the content-hash
        # key meaningful for lines without a bank reference.
        **({"purpose": purpose} if purpose else {}),
    }
    return StatementLine(
        amount=amount,
        currency=entry.currency,
        booking_date=entry.booking_date,
        value_date=entry.value_date,
        purpose=purpose,
        counterparty_name=cp_name,
        counterparty_iban=cp_iban,
        end_to_end_id=clean(skip_notprovided(_find_text_local(scope, "EndToEndId"))),
        reference=clean(_find_text_local(scope, "InstrId")),
        bank_ref=bank_ref,
        raw=raw,
    )


def _purpose_text(scope: ET.Element, ntry: ET.Element) -> str | None:
    """Return the purpose of a scope.

    The purpose is every `Ustrd` line joined, because banks split a long purpose across
    several elements. Without `Ustrd` the parser falls back to the `AddtlNtryInf` of the
    entry. Sparkasse puts text such as "SAMMELUEBERWEISUNG DATEI-NR. …" there.
    """
    parts = [t for el in _findall_local(scope, "Ustrd") if (t := clean(el.text))]
    if parts:
        return " ".join(parts)
    return clean(_find_text_local(ntry, "AddtlNtryInf"))


def camt_closing_balance(data: bytes) -> StatementBalance | None:
    """Return the CAMT closing balance.

    The balance is the `<Bal>` element with code `CLBD` (Closing Booked). The sign comes
    from `CdtDbtInd`. Without a CLBD entry the parser falls back to `CLAV` (Closing
    Available).

    Returns:
        The closing balance, or `None` when the XML is broken or holds no usable
        balance.
    """
    try:
        root = ET.fromstring(data)  # noqa: S314 - own statement, no external entities
    except ET.ParseError:
        return None
    by_code: dict[str, ET.Element] = {}
    for bal in _findall_local(root, "Bal"):
        code = (_find_text_local(bal, "Cd") or "").upper()
        if code:
            # With several <Stmt> (multi-day export) the LAST closing balance wins.
            by_code[code] = bal
    # `Element or Element` trips the ElementTree truthiness deprecation. Check it
    # explicitly.
    chosen = by_code.get("CLBD")
    if chosen is None:
        chosen = by_code.get("CLAV")
    if chosen is None:
        return None
    amt_el = _find_local(chosen, "Amt")
    if amt_el is None or not (amt_el.text or "").strip():
        return None
    try:
        magnitude = sane_amount(Decimal((amt_el.text or "").strip()))
    except (InvalidOperation, ValueError, StatementParseError):
        return None
    ind = (_find_text_local(chosen, "CdtDbtInd") or "").upper()
    amount = -abs(magnitude) if ind.startswith("DBIT") else abs(magnitude)
    return StatementBalance(
        amount=amount,
        currency=(amt_el.get("Ccy") or "EUR").upper(),
        as_of=_camt_date(_find_local(chosen, "Dt")),
    )


def _local(tag: str) -> str:
    """Return the local tag name without the `{namespace}` prefix."""
    return tag.rsplit("}", 1)[-1]


def _find_local(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    for child in el.iter():
        if child is not el and _local(child.tag) == name:
            return child
    return None


def _findall_local(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el.iter() if _local(c.tag) == name]


def _find_text_local(el: ET.Element | None, name: str) -> str | None:
    found = _find_local(el, name)
    return found.text if found is not None else None


def _camt_date(el: ET.Element | None) -> date | None:
    """Convert a CAMT `BookgDt` or `ValDt` to a `date` (`Dt` = YYYY-MM-DD, or `DtTm`)."""
    if el is None:
        return None
    raw = _find_text_local(el, "Dt") or _find_text_local(el, "DtTm")
    if not raw or len(raw) < 10:
        return None
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        return None
