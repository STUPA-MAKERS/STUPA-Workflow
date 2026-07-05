"""FinTS online-banking client — transaction fetch with PIN/TAN SCA.

Wraps the ``fints`` lib (lazily imported) behind two steps, because PSD2 strong
customer authentication requires a TAN that arrives from a human BETWEEN two
HTTP requests: :func:`start_sync` opens the dialog and requests transactions,
returning either the lines (``status='done'``) or a paused dialog state + TAN
challenge (``status='needs_tan'``); :func:`submit_tan` resumes the paused dialog
and sends the TAN (or an empty TAN to poll for decoupled pushTAN).

Transactions are fetched preferably as CAMT (HKCAZ, ``get_transactions_xml``):
only CAMT carries the single transactions (``TxDtls``) of batch bookings, which
:mod:`.camt_parse` splits. Banks without HKCAZ (or with unusable CAMT) fall back
to MT940 (HKKAZ) automatically.

The persistent client state (``deconstruct()``: ``system_id`` etc.) is returned
after a successful sync and stored encrypted by the service — this keeps the
~90-day SCA window open.

The network interaction is untestable without a real bank (``# pragma: no
cover``); the pure logic (TAN-mechanism choice, account selection, line
normalization, result shape) stays covered.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from app.modules.budget.bank.camt_parse import parse_camt, statement_account_ids
from app.modules.budget.bank.mt940_parse import (
    balance_from_mt940,
    lines_from_mt940_transactions,
)
from app.modules.budget.bank.statement import (
    StatementBalance,
    StatementLine,
    StatementParseError,
)
from app.modules.webhooks.ssrf import Resolver, SsrfError, assert_allowed_url, default_resolver

if TYPE_CHECKING:
    from fints.client import FinTS3PinTanClient, NeedTANResponse

logger = logging.getLogger(__name__)


class FintsError(RuntimeError):
    """FinTS fetch failed (connection, login, protocol)."""


class FintsBankLockedError(FintsError):
    """Bank locked the access (e.g. after 3 failed attempts, FinTS code 3938).

    Do NOT retry automatically — every further login counts against the bank's
    failed-attempt account and can escalate the lock until only the bank
    (hotline/branch or online-banking unlock) can lift it."""


class FintsAccountSelectionError(FintsError):
    """The configured account could not be matched among the bank's SEPA accounts
    (and the login has more than one), so the correct account is ambiguous. Not a
    bank/auth error — surfaced to the user as "set the IBAN on this account",
    never a lock. Do NOT fall back to fetching an arbitrary account."""


class FintsAuthRejectedError(FintsError):
    """Bank rejected login/signature (FinTS codes 9340/9910/9930/9931/9942).

    python-fints misleadingly reports these as "wrong PIN" and then blocks the
    PIN instance. The cause is often the signature (wrong/missing TAN mechanism,
    missing product id), not necessarily the PIN. Clarify the cause before
    retrying — a few attempts away from a bank lock."""


def _classify(exc: BaseException) -> FintsError:
    """Map lib/bank errors to our error types (detect bank locks).

    The WHOLE exception chain (``__cause__``/``__context__``) is searched, not
    just the outermost exception: on 9340 python-fints blocks the PIN instance
    and the ``with client:`` teardown then raises ``Exception("Refusing to use
    PIN after block")`` at final signing — masking the actual
    ``FinTSClientPINError``. Without the chain walk, the bank rejection would be
    reported as a generic 503 instead of 409+cooldown.

    The lib/bank message text is NOT adopted (may carry request/response
    fragments or PIN/TAN); only the error TYPE decides. ``fints`` is imported
    lazily so the pure contract path does not need the lib."""
    from fints.exceptions import FinTSClientPINError, FinTSClientTemporaryAuthError

    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, FinTSClientTemporaryAuthError):
            return FintsBankLockedError("FinTS access is temporarily locked by the bank.")
        if isinstance(cur, FinTSClientPINError):
            return FintsAuthRejectedError("FinTS authentication was rejected by the bank.")
        cur = cur.__cause__ or cur.__context__
    return FintsError("FinTS sync failed.")


# Allowed MIME types for the optical TAN challenge (photoTAN/QR-TAN as ``<img>``).
_ALLOWED_TAN_IMAGE_MIME = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
)


def validate_fints_endpoint(url: str, *, resolver: Resolver = default_resolver) -> None:
    """Check the FinTS endpoint against SSRF.

    Enforces ``https`` (FinTS runs over TLS) and delegates the host/IP check to
    the existing hardened ``assert_allowed_url`` guard (resolves DNS, checks all
    A/AAAA records, unwraps IPv4-mapped/6to4/NAT64 and blocks every non-global
    address). ``resolver`` is injectable for tests.

    :raises ValueError: scheme is not https, or rejected by the SSRF guard.
    """
    if urlsplit(url).scheme.lower() != "https":
        raise ValueError("FinTS endpoint must use https")
    try:
        assert_allowed_url(url, resolver=resolver)
    except SsrfError as exc:
        raise ValueError(f"FinTS endpoint not allowed: {exc}") from exc


@dataclass(slots=True)
class FintsOutcome:
    """Result of one sync step — done OR TAN required."""

    status: Literal["done", "needs_tan"]
    tan_mechanism: str | None = None
    # status == 'done':
    lines: list[StatementLine] = field(default_factory=list)
    new_state: bytes | None = None  # client.deconstruct() -> persist
    # Live balance (HKSAL) at fetch time — best effort.
    balance: StatementBalance | None = None
    # status == 'needs_tan' (all required for the resume):
    client_data: bytes | None = None
    dialog_data: bytes | None = None
    tan_data: bytes | None = None
    challenge: str | None = None
    challenge_html: str | None = None
    # Optical challenge (photoTAN/QR-TAN) as a ready data URL
    # ``data:<mime>;base64,…`` for direct display in an ``<img>``.
    challenge_image: str | None = None
    decoupled: bool = False
    # True when the TAN is needed for the LOGIN itself (SCA with a fresh
    # system_id) — then ``submit_tan`` must fetch accounts + transactions after
    # the confirmation (with a data TAN, ``send_tan`` delivers them directly).
    tan_for_login: bool = False
    # Account scope of the paused transactions fetch (selected SEPA account's
    # IBAN/number): ``submit_tan`` re-uses it to scope the resumed CAMT result —
    # the SEPAAccount is not re-resolved on resume, and the configured IBAN
    # alone can be empty (older Sparkasse accounts without IBAN).
    account_scope: tuple[str, ...] = ()


@dataclass(slots=True)
class FintsCredentials:
    """Connection/login data of an account (PIN in plaintext, memory only)."""

    endpoint: str
    blz: str
    login: str
    pin: str
    account_iban: str | None = None
    product_id: str | None = None
    tan_mechanism: str | None = None
    state: bytes | None = None  # last persisted client state
    start_date: date | None = None  # fetch-window start (set by the service)


def _pick_tan_mechanism(mechanisms: Mapping[str, object], preferred: str | None) -> str | None:
    """Pick a TAN mechanism: previously used, else decoupled/pushTAN, else first.

    ``mechanisms`` = ``{security_function: TwoStepParameters}`` from
    ``client.get_tan_mechanisms()``."""
    if not mechanisms:
        return None
    if preferred and preferred in mechanisms:
        return preferred
    for sec_func, params in mechanisms.items():
        name = str(getattr(params, "name", "") or "").lower()
        if getattr(params, "decoupled", False) or "push" in name or "decoupled" in name:
            return sec_func
    return next(iter(mechanisms))


def _norm_iban(value: object) -> str:
    return str(value or "").replace(" ", "").upper()


def _kto_from_de_iban(iban: str) -> str:
    """The account number embedded in a German IBAN (leading zeros stripped).

    ``DEkk BBBBBBBB KKKKKKKKKK`` — the last 10 digits are the account number.
    Empty for non-DE / malformed IBANs (nothing to match by)."""
    return iban[12:22].lstrip("0") if len(iban) == 22 and iban.startswith("DE") else ""


def _norm_kto(value: object) -> str:
    return str(value or "").strip().lstrip("0")


def _select_account(accounts: Sequence[object], iban: str | None):  # type: ignore[no-untyped-def]  # noqa: ANN202
    """Pick the SEPA account matching the configured ``iban``.

    Matches by IBAN, then — because Sparkasse & co. frequently return SEPA
    accounts with an EMPTY iban (only KTO/BLZ) — by the account number embedded
    in the German IBAN vs the account's ``accountnumber``. With a single account
    on the login the choice is unambiguous and returned regardless. With several
    accounts and no confident match we raise instead of silently fetching a
    random account (which would stage a FOREIGN account's bookings under this
    one). Empty account list raises ``FintsError``."""
    accs = list(accounts)
    if not accs:
        raise FintsError("bank returned no SEPA accounts")
    want = _norm_iban(iban)
    if want:
        for acc in accs:
            if _norm_iban(getattr(acc, "iban", None)) == want:
                return acc
        kto = _kto_from_de_iban(want)
        if kto:
            for acc in accs:
                if _norm_kto(getattr(acc, "accountnumber", None)) == kto:
                    return acc
    if len(accs) == 1:
        return accs[0]
    raise FintsAccountSelectionError(
        "could not match the configured account among the bank's SEPA accounts"
    )


def lines_from_camt_documents(
    documents: Sequence[bytes], account_ids: Collection[str] = ()
) -> list[StatementLine]:
    """Convert CAMT documents of an HKCAZ fetch into lines.

    ``account_ids`` scopes each document to the selected account (a combined
    camt.053 can carry several accounts' statements). A well-formed document
    WITHOUT entries (empty day/fetch window, or all statements filtered out)
    counts as 0 lines; broken XML raises :class:`StatementParseError` (the client
    then falls back to MT940)."""
    lines: list[StatementLine] = []
    for doc in documents:
        if not doc:
            continue
        try:
            lines.extend(parse_camt(doc, account_ids=account_ids))
        except StatementParseError as exc:
            if "no entries" in str(exc) or "no usable entries" in str(exc):
                continue
            raise
    return lines


def lines_from_fetch_result(
    result: object, account_ids: Collection[str] = ()
) -> list[StatementLine]:
    """Convert a ``fints`` fetch result into lines, shape-agnostic.

    ``get_transactions_xml`` returns ``(booked_xml_docs, pending)``;
    ``get_transactions`` (and ``send_tan`` for an MT940 job) returns ``mt940``
    transactions. ``send_tan`` passes through the ORIGINAL job's result, so the
    TAN resume must accept both shapes. ``account_ids`` scopes the CAMT path to one
    account; the MT940 live fetch (HKKAZ) is already per-account."""
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], (list, tuple))
    ):
        booked = [doc for doc in result[0] if isinstance(doc, (bytes, bytearray))]
        return lines_from_camt_documents([bytes(doc) for doc in booked], account_ids)
    return lines_from_mt940_transactions(result)


# --------------------------------------------------------------------- network
def _build_client(creds: FintsCredentials) -> FinTS3PinTanClient:  # pragma: no cover
    from fints.client import FinTS3PinTanClient

    return FinTS3PinTanClient(
        creds.blz,
        creds.login,
        creds.pin,
        creds.endpoint,
        product_id=creds.product_id,
        from_data=creds.state,
    )


def _matrix_data_url(response: object) -> str | None:
    """Convert the optical TAN challenge (photoTAN/QR-TAN) into a data URL.

    ``NeedTANResponse.challenge_matrix`` is ``(mime: str, data: bytes)`` or
    ``None``; malformed/empty values yield ``None`` (text challenge + TAN input only)."""
    matrix = getattr(response, "challenge_matrix", None)
    if not matrix:
        return None
    try:
        mime, data = matrix
    except (TypeError, ValueError):
        return None
    if not data:
        return None
    # Do NOT blindly adopt the bank-supplied MIME type — only known image types go
    # into the data URL (defense in depth for the ``<img>`` binding), else default.
    candidate = str(mime or "").lower().strip()
    mime = candidate if candidate in _ALLOWED_TAN_IMAGE_MIME else "image/png"
    return f"data:{mime};base64,{base64.b64encode(bytes(data)).decode('ascii')}"


def _needs_tan(
    client: FinTS3PinTanClient,
    response: NeedTANResponse,
    mechanism: str | None,
    *,
    for_login: bool = False,
    account_scope: Collection[str] = (),
) -> FintsOutcome:  # pragma: no cover
    """Pause the dialog and collect everything needed for the later resume."""
    dialog_data = client.pause_dialog()
    return FintsOutcome(
        status="needs_tan",
        tan_mechanism=mechanism,
        client_data=client.deconstruct(including_private=True),
        dialog_data=dialog_data,
        tan_data=response.get_data(),
        challenge=getattr(response, "challenge", None),
        challenge_html=str(getattr(response, "challenge_html", "") or "") or None,
        challenge_image=_matrix_data_url(response),
        decoupled=bool(getattr(response, "decoupled", False)),
        tan_for_login=for_login,
        account_scope=tuple(account_scope),
    )


def _account_scope(account: object, creds: FintsCredentials) -> frozenset[str]:
    """Identifiers the fetch is scoped to: the selected SEPA account's IBAN AND
    account number (bank ground truth), plus the configured account IBAN and the
    number embedded in it. The number is included because older Sparkasse SEPA
    accounts expose no IBAN — an IBAN-only scope would then be empty and let every
    account's bookings through. Account numbers are matched with leading zeros
    stripped (as in the CAMT statement)."""
    ids: set[str] = set()
    for iban in (getattr(account, "iban", None), creds.account_iban):
        if n := _norm_iban(iban):
            ids.add(n)
    if kto := _norm_kto(getattr(account, "accountnumber", None)):
        ids.add(kto)
    if kto := _kto_from_de_iban(_norm_iban(creds.account_iban)):
        ids.add(kto)
    return frozenset(ids)


def _mask_id(value: str) -> str:
    """Mask an account identifier for logs — last 4 chars only, never the full IBAN."""
    return f"…{value[-4:]}" if len(value) >= 4 else "…"


def _fetch_lines(
    client: FinTS3PinTanClient, account: object, start: date, account_ids: Collection[str]
) -> object:  # pragma: no cover
    """Fetch transactions: CAMT (HKCAZ) preferred, MT940 (HKKAZ) as fallback.

    ``account_ids`` scopes the CAMT result to the selected account (a combined
    camt.053 may carry several accounts). Returns either the finished lines
    (``list[StatementLine]``) or the fetch's ``NeedTANResponse``."""
    from fints.client import NeedTANResponse
    from fints.exceptions import FinTSUnsupportedOperation

    end = date.today()
    logger.info("FinTS fetch scope (masked): %s", sorted(_mask_id(i) for i in account_ids) or "ALL")
    try:
        response = client.get_transactions_xml(account, start, end)  # type: ignore[arg-type]
    except FinTSUnsupportedOperation:
        logger.info("FinTS: bank does not support HKCAZ (camt) — falling back to MT940")
        response = None
    if response is not None:
        if isinstance(response, NeedTANResponse):
            return response
        _log_camt_accounts(response)
        try:
            return lines_from_fetch_result(response, account_ids)
        except StatementParseError:
            # Broken CAMT: better MT940 than no fetch; do NOT log the contents
            # (transaction data). The fallback normalizes via the same path.
            logger.warning("FinTS: camt statements unparseable — falling back to MT940")
    response = client.get_transactions(account, start, end)  # type: ignore[arg-type]
    if isinstance(response, NeedTANResponse):
        return response
    return lines_from_mt940_transactions(response)


def _log_camt_accounts(response: object) -> None:  # pragma: no cover
    """Log which accounts the fetched CAMT actually contains (masked ids) — makes
    an all-accounts fetch vs an empty scope conclusive from a single live run."""
    if not (
        isinstance(response, tuple)
        and len(response) == 2
        and isinstance(response[0], (list, tuple))
    ):
        return
    for doc in response[0]:
        if isinstance(doc, (bytes, bytearray)):
            ids = [_mask_id(i) for i in statement_account_ids(bytes(doc))]
            logger.info("FinTS camt document statement accounts (masked): %s", ids)


def _fetch(
    client: FinTS3PinTanClient, creds: FintsCredentials, mechanism: str | None
) -> FintsOutcome:  # pragma: no cover
    """Within an open dialog: fetch accounts + transactions, catch TAN interrupts."""
    from fints.client import NeedTANResponse

    accounts = client.get_sepa_accounts()
    if isinstance(accounts, NeedTANResponse):
        return _needs_tan(client, accounts, mechanism)
    acct_list = list(accounts)
    # Diagnostics (masked, last-4 only): the accounts the bank returned (IBAN|KTO)
    # and the configured account — reveals a wrong-account selection at a glance.
    available = [
        f"{_mask_id(_norm_iban(getattr(a, 'iban', None)))}"
        f"|{_mask_id(_norm_kto(getattr(a, 'accountnumber', None)))}"
        for a in acct_list
    ]
    logger.info(
        "FinTS: %d SEPA account(s) returned; configured=%s; available=%s",
        len(acct_list),
        _mask_id(_norm_iban(creds.account_iban)),
        available,
    )
    account = _select_account(acct_list, creds.account_iban)
    # Fetch window: from ``start_date`` (capped by the service) until today.
    start = creds.start_date or date.today()
    scope = _account_scope(account, creds)
    result = _fetch_lines(client, account, start, scope)
    if isinstance(result, NeedTANResponse):
        # Keep the resolved scope for the resume: ``submit_tan`` parses the
        # paused job's result without re-selecting the SEPA account.
        return _needs_tan(client, result, mechanism, account_scope=scope)
    return FintsOutcome(
        status="done",
        tan_mechanism=mechanism,
        lines=list(result),  # type: ignore[arg-type]
        balance=_live_balance(client, account),
    )


def _live_balance(  # pragma: no cover
    client: FinTS3PinTanClient, account: object
) -> StatementBalance | None:
    """Fetch the HKSAL balance best-effort — errors/TAN demands are swallowed
    (the balance is optional; the transactions take precedence)."""
    from fints.client import NeedTANResponse

    try:
        bal = client.get_balance(account)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - balance is optional, never fail the fetch
        return None
    if isinstance(bal, NeedTANResponse) or bal is None:
        return None
    return balance_from_mt940(bal)


def start_sync(creds: FintsCredentials, *, start_date: date) -> FintsOutcome:  # pragma: no cover
    """Step 1: open the dialog and request transactions from ``start_date``."""
    creds.start_date = start_date
    client = _build_client(creds)
    try:
        # IMPORTANT: fetch TAN mechanisms over the NETWORK first
        # (``fetch_tan_mechanisms``) — that populates BPD + allowed security
        # functions + system_id. Plain ``get_tan_mechanisms`` only reads the BPD,
        # which is EMPTY on a fresh client (``from_data=None`` — the case after
        # every credential set) and returns ``{}`` — no two-step mechanism would
        # be chosen and python-fints would sign with one-step PIN. Sparkassen
        # (PSD2) reject that with "9340 invalid signature" — misreported by the
        # lib as "wrong PIN", which locks the bank account after 3 attempts.
        from fints.client import NeedTANResponse

        client.fetch_tan_mechanisms()
        mechanisms = client.get_tan_mechanisms()
        mechanism = _pick_tan_mechanism(dict(mechanisms), creds.tan_mechanism)
        # Diagnostics (NO secrets): TAN mechanism count + chosen security
        # function. Empty/None means one-step signing and a Sparkasse "9340" —
        # this makes a single live test conclusive without risking blind retries.
        logger.info(
            "FinTS start_sync: %d TAN mechanism(s) available, selected=%s",
            len(mechanisms),
            mechanism,
        )
        if mechanism:
            client.set_tan_mechanism(mechanism)
        with client:
            # With a fresh ``system_id`` (after every credential set) the bank
            # demands SCA for the LOGIN itself: python-fints then sets
            # ``init_tan_response`` at dialog init. Without that confirmation,
            # ``get_sepa_accounts`` runs on a non-strongly-authenticated login —
            # "9340 invalid signature". So request the login TAN first; the
            # transactions are fetched by ``submit_tan`` after confirmation.
            login_tan = client.init_tan_response
            logger.info(
                "FinTS start_sync: login SCA required=%s", isinstance(login_tan, NeedTANResponse)
            )
            if isinstance(login_tan, NeedTANResponse):
                outcome = _needs_tan(client, login_tan, mechanism, for_login=True)
            else:
                outcome = _fetch(client, creds, mechanism)
        # The dialog is closed (unless paused) — save the persistent state.
        if outcome.status == "done":
            outcome.new_state = client.deconstruct(including_private=True)
        return outcome
    except FintsError:
        raise
    except Exception as exc:  # noqa: BLE001 — wrap lib/network errors uniformly
        # Log the original error server-side ONLY — the lib/bank text can contain
        # request/response fragments, and PIN/TAN are in scope here.
        logger.warning("FinTS sync failed", exc_info=exc)
        raise _classify(exc) from exc


def submit_tan(  # pragma: no cover
    creds: FintsCredentials, pending: FintsOutcome, tan: str
) -> FintsOutcome:
    """Step 2: resume the paused dialog and send the TAN (empty = decoupled poll)."""
    from fints.client import NeedRetryResponse, NeedTANResponse

    if pending.client_data is None or pending.dialog_data is None or pending.tan_data is None:
        raise FintsError("incomplete pending-TAN state")
    creds.state = pending.client_data
    client = _build_client(creds)
    try:
        if pending.tan_mechanism:
            client.set_tan_mechanism(pending.tan_mechanism)
        tan_response = NeedRetryResponse.from_data(pending.tan_data)
        # python-fints' get_data()/from_data() does NOT round-trip the decoupled
        # flag (NeedTANResponse._from_data_v1 rebuilds with decoupled=False). We
        # persist it ourselves (FintsOutcome.decoupled) and MUST restore it here:
        # otherwise send_tan() takes the non-decoupled branch and submits our empty
        # poll TAN as a normal process-'2' TAN, which the bank rejects ("9xxx") —
        # misreported as an auth rejection + lock cooldown on every pushTAN poll.
        if pending.decoupled and isinstance(tan_response, NeedTANResponse):
            tan_response.decoupled = True
        with client.resume_dialog(pending.dialog_data):
            result = client.send_tan(tan_response, tan)
            if isinstance(result, NeedTANResponse):
                # Another TAN needed (e.g. decoupled not yet approved) — keep the flag.
                return _needs_tan(
                    client, result, pending.tan_mechanism, for_login=pending.tan_for_login
                )
            if pending.tan_for_login:
                # Login SCA confirmed — only NOW fetch accounts + transactions
                # (the data step may itself demand a TAN: data TAN, for_login=False).
                outcome = _fetch(client, creds, pending.tan_mechanism)
                if outcome.status == "done":
                    outcome.new_state = client.deconstruct(including_private=True)
                return outcome
            # ``send_tan`` returns the paused job's result — a CAMT tuple or MT940
            # transactions, depending on which fetch demanded the TAN. Scope the
            # CAMT path to the account scope resolved at ``start_sync`` (the
            # selected SEPAAccount is not re-resolved on resume); fall back to
            # the configured IBAN for sessions persisted before the scope existed.
            scope = list(pending.account_scope) or (
                [creds.account_iban] if creds.account_iban else []
            )
            lines = lines_from_fetch_result(result, scope)
        return FintsOutcome(
            status="done",
            tan_mechanism=pending.tan_mechanism,
            lines=lines,
            new_state=client.deconstruct(including_private=True),
        )
    except FintsError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("FinTS TAN submission failed", exc_info=exc)
        raise _classify(exc) from exc
