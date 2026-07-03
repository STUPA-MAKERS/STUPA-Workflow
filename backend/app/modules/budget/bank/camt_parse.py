"""CAMT.052/053 statements (XML) to :class:`~.statement.StatementLine`.

Namespace-tolerant (via local name) and version-tolerant (any
``camt.05x.001.yy``). Batch bookings — one ``Ntry`` with several ``TxDtls`` —
are split into single transactions, one line per ``TxDtls`` with its own
amount/purpose/counterparty. Split only when the partial amounts add up exactly
to the entry amount; otherwise conservatively keep one line with the total.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
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


def parse_camt(data: bytes, iban: str | None = None) -> list[StatementLine]:
    """Parse a CAMT statement (report ``camt.052`` or statement ``camt.053``).

    ``iban`` (optional) scopes the result to one account: a single HKCAZ fetch can
    return a COMBINED camt.053 with one ``<Stmt>`` per account of the login, and
    without scoping every account's bookings would be merged (and staged under the
    one selected account). When ``iban`` is set, statements identifying a
    DIFFERENT account are skipped; statements without an identifiable IBAN (and
    ``iban=None``) are always kept, so file imports and minimal docs are unaffected.

    :raises StatementParseError: missing/broken CAMT XML or no usable entries."""
    try:
        root = ET.fromstring(data)  # noqa: S314 - own statement, no external entities
    except ET.ParseError as exc:
        raise StatementParseError(f"unparseable CAMT XML: {exc}") from exc

    entries = _scoped_entries(root, iban)
    if not entries:
        raise StatementParseError("CAMT XML contained no entries (Ntry)")

    lines: list[StatementLine] = []
    for ntry in entries:
        lines.extend(_lines_from_entry(ntry))
    if not lines:
        raise StatementParseError("CAMT XML contained no usable entries")
    return lines


def _scoped_entries(root: ET.Element, iban: str | None) -> list[ET.Element]:
    """The ``Ntry`` elements, limited to the statement(s) of ``iban`` when given.

    camt.053 groups bookings under one ``<Stmt>`` per account (camt.052 under
    ``<Rpt>``), each carrying its own ``<Acct>/<IBAN>``. Drop a statement only when
    it has an IBAN that does NOT match — never when the IBAN is absent or no
    scope was requested (avoids an empty fetch if a bank omits/varies the IBAN).
    A doc without any statement container falls back to a flat ``Ntry`` scan."""
    want = (iban or "").replace(" ", "").upper()
    statements = _findall_local(root, "Stmt") + _findall_local(root, "Rpt")
    if not statements:
        return _findall_local(root, "Ntry")
    entries: list[ET.Element] = []
    for stmt in statements:
        if want:
            # The statement's own account is the first <Acct> in document order;
            # counterparty accounts are <DbtrAcct>/<CdtrAcct>, not <Acct>.
            stmt_iban = (
                _find_text_local(_find_local(stmt, "Acct"), "IBAN") or ""
            ).replace(" ", "").upper()
            if stmt_iban and stmt_iban != want:
                continue
        entries.extend(_findall_local(stmt, "Ntry"))
    return entries


@dataclass(slots=True)
class _Entry:
    """Pre-digested ``Ntry`` facts shared by every line derived from it."""

    amount: Decimal  # signed (incl. reversal flip)
    orig_credit: bool  # the entry's CdtDbtInd (original direction)
    reversal: bool
    currency: str
    booking_date: date | None
    value_date: date | None
    bank_ref: str | None


def _entry_facts(ntry: ET.Element) -> _Entry | None:
    """Read amount/direction/reversal/dates of one ``Ntry`` — ``None`` = unusable."""
    amt_el = _find_local(ntry, "Amt")
    if amt_el is None or not (amt_el.text or "").strip():
        return None
    try:
        magnitude = Decimal((amt_el.text or "").strip())
    except (InvalidOperation, ValueError):
        return None
    # Require the direction explicitly: without a clear CRDT/DBIT the economic
    # direction is unknown — do not silently assume outflow.
    ind = (_find_text_local(ntry, "CdtDbtInd") or "").upper()
    if ind.startswith("CRDT"):
        orig_credit = True
    elif ind.startswith("DBIT"):
        orig_credit = False
    else:
        return None
    # A reversal (``RvslInd=true``) flips the economic direction (chargeback).
    reversal = (_find_text_local(ntry, "RvslInd") or "").strip().lower() in ("true", "1")
    credit = (not orig_credit) if reversal else orig_credit
    # CAMT ``<Amt>`` is >= 0 per spec; a negative value would flip the sign again
    # below — defensively decouple the amount (direction comes only from the indicator).
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
    """Map one ``Ntry`` to 1 line (single booking) or n lines (split batch booking)."""
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
    """Resolve a batch booking into single transactions — or ``None`` if unsafe.

    Safe means: every ``TxDtls`` carries its own ``TxAmt`` in the entry currency
    and the signed partial amounts sum exactly to the entry amount — otherwise
    the split would invent amounts (e.g. gross/net deviation due to fees).
    """
    lines: list[StatementLine] = []
    total = Decimal("0")
    for tx in tx_details:
        amount = _tx_amount(tx, entry)
        if amount is None:
            return None
        # Bank reference per sub-transaction (if any). The entry reference is
        # identical for all parts and must NOT be used — all sub-lines would
        # collapse onto the same idempotency key.
        tx_ref = clean(_find_text_local(_find_local(tx, "Refs"), "AcctSvcrRef"))
        lines.append(_line_from_scope(tx, ntry, entry, amount=amount, bank_ref=tx_ref))
        total += amount
    if total != entry.amount:
        return None
    batch_meta = {
        "batch": "true",
        "batch_count": str(len(tx_details)),
        "batch_total": str(entry.amount),
        **({"batch_ref": entry.bank_ref} if entry.bank_ref else {}),
    }
    for line in lines:
        line.raw.update(batch_meta)
    return lines


def _tx_amount(tx: ET.Element, entry: _Entry) -> Decimal | None:
    """Signed amount of a sub-transaction (``AmtDtls/TxAmt/Amt``).

    ``None`` when amount/currency are missing or do not match the entry currency.
    Direction comes from the sub-transaction's ``CdtDbtInd``, else the entry's;
    an entry reversal flips it (as for the unsplit entry)."""
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
    """Build one line from a detail scope (``TxDtls`` or the ``Ntry`` itself)."""
    credit = amount > 0
    # The counterparty follows the ORIGINAL direction (Dbtr/Cdtr in the XML refer
    # to it) — on credit the debtor (payer), otherwise the creditor.
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
        # Record the raw purpose: feeds ``resolve_purpose`` and makes the
        # content-hash key meaningful (lines without a bank reference).
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
    """Purpose of a scope: all ``Ustrd`` lines joined (banks split long purposes
    across elements); without ``Ustrd``, the entry's ``AddtlNtryInf`` (Sparkasse
    puts e.g. "SAMMELUEBERWEISUNG DATEI-NR. …" there)."""
    parts = [t for el in _findall_local(scope, "Ustrd") if (t := clean(el.text))]
    if parts:
        return " ".join(parts)
    return clean(_find_text_local(ntry, "AddtlNtryInf"))


# ------------------------------------------------------------------------ balance
def camt_closing_balance(data: bytes) -> StatementBalance | None:
    """CAMT closing balance: ``<Bal>`` with code ``CLBD`` (Closing Booked); sign
    from ``CdtDbtInd``. Falls back to ``CLAV`` (Closing Available) without CLBD."""
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
    # `Element or Element` trips the ElementTree truthiness deprecation — check explicitly.
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


# -------------------------------------------------------------------- XML helpers
def _local(tag: str) -> str:
    """Local tag name without the ``{namespace}`` prefix."""
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
    """CAMT ``BookgDt``/``ValDt`` to ``date`` (``Dt`` = YYYY-MM-DD, or ``DtTm``)."""
    if el is None:
        return None
    raw = _find_text_local(el, "Dt") or _find_text_local(el, "DtTm")
    if not raw or len(raw) < 10:
        return None
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        return None
