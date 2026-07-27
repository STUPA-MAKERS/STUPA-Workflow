"""FinTS online-banking client: transaction fetch with PIN/TAN SCA.

This module wraps the `fints` lib (imported lazily) behind two steps. PSD2 strong
customer authentication needs a TAN that a human enters BETWEEN two HTTP requests.
`start_sync` opens the dialog and requests the transactions. It returns either the lines
(`status='done'`) or a paused dialog state with a TAN challenge (`status='needs_tan'`).
`submit_tan` resumes the paused dialog and sends the TAN. An empty TAN polls for a
decoupled pushTAN.

The client prefers CAMT for the fetch (HKCAZ, `get_transactions_xml`). Only CAMT carries
the single transactions (`TxDtls`) of a batch booking, which `camt_parse` splits. A bank
without HKCAZ, or with unusable CAMT, falls back to MT940 (HKKAZ) automatically.

After a successful sync the client returns the persistent state (`deconstruct()`, for
example `system_id`). The service stores it encrypted. This keeps the SCA window of
about 90 days open.

The network code needs a real bank, so it carries `# pragma: no cover`. The pure logic
stays covered: TAN-mechanism choice, account selection, line normalization and result
shape.
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
    """The bank locked the access (for example after 3 failed attempts, FinTS code 3938).

    Do NOT retry automatically. Every further login counts against the failed-attempt
    counter of the bank. It can escalate the lock until only the bank can lift it,
    through the hotline, a branch or an online-banking unlock.
    """


class FintsAccountSelectionError(FintsError):
    """The configured account matches no SEPA account of the bank.

    The login has more than one account, so the correct account is ambiguous. This is
    not a bank error and not an auth error. The user sees "set the IBAN on this
    account", never a lock. Do NOT fall back to fetching an arbitrary account.
    """


class FintsAuthRejectedError(FintsError):
    """The bank rejected the login or the signature (FinTS codes 9340/9910/9930/9931/9942).

    The python-fints lib reports these codes as "wrong PIN" and then blocks the PIN
    instance. That report misleads. The cause is often the signature, for example a
    wrong or missing TAN mechanism, or a missing product id. The PIN is not always the
    cause. Find the cause before you retry. A bank lock is only a few attempts away.
    """


def _classify(exc: BaseException) -> FintsError:
    """Map lib and bank errors to our error types and detect a bank lock.

    The function searches the WHOLE exception chain (`__cause__` and `__context__`), not
    only the outermost exception. On 9340 python-fints blocks the PIN instance. The
    `with client:` teardown then raises `Exception("Refusing to use PIN after block")` at
    the final signing, which masks the real `FinTSClientPINError`. Without the chain
    walk, the code would report the bank rejection as a generic 503 instead of a 409
    with a cooldown.

    The function does NOT adopt the message text of the lib or the bank. That text can
    carry request or response fragments, or a PIN or TAN. Only the error TYPE decides.
    The `fints` import is lazy, so the pure contract path does not need the lib.
    """
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


# Allowed MIME types for the optical TAN challenge (photoTAN or QR-TAN as `<img>`).
_ALLOWED_TAN_IMAGE_MIME = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
)


def validate_fints_endpoint(url: str, *, resolver: Resolver = default_resolver) -> None:
    """Check the FinTS endpoint against SSRF.

    The function requires `https`, because FinTS runs over TLS. It delegates the host
    and IP check to the hardened `assert_allowed_url` guard. That guard resolves DNS,
    checks all A and AAAA records, unwraps IPv4-mapped, 6to4 and NAT64 addresses, and
    blocks every non-global address.

    A test can inject its own `resolver`.

    Raises:
        ValueError: The scheme is not https, or the SSRF guard rejected the URL.
    """
    if urlsplit(url).scheme.lower() != "https":
        raise ValueError("FinTS endpoint must use https")
    try:
        assert_allowed_url(url, resolver=resolver)
    except SsrfError as exc:
        raise ValueError(f"FinTS endpoint not allowed: {exc}") from exc


@dataclass(slots=True)
class FintsOutcome:
    """Result of one sync step: done OR TAN required."""

    status: Literal["done", "needs_tan"]
    tan_mechanism: str | None = None
    # Filled when status is 'done':
    lines: list[StatementLine] = field(default_factory=list)
    new_state: bytes | None = None  # from client.deconstruct(), the service persists it
    # Live balance (HKSAL) at fetch time, best effort.
    balance: StatementBalance | None = None
    # Filled when status is 'needs_tan' (the resume needs all of them):
    client_data: bytes | None = None
    dialog_data: bytes | None = None
    tan_data: bytes | None = None
    challenge: str | None = None
    challenge_html: str | None = None
    # Optical challenge (photoTAN or QR-TAN) as a ready data URL
    # `data:<mime>;base64,…` for direct display in an `<img>` element.
    challenge_image: str | None = None
    decoupled: bool = False
    # True when the TAN is needed for the LOGIN itself (SCA with a fresh system_id).
    # Then `submit_tan` must fetch the accounts and transactions after the confirmation.
    # With a data TAN, `send_tan` delivers them directly.
    tan_for_login: bool = False
    # Account scope of the paused transactions fetch: the IBAN and number of the
    # selected SEPA account. `submit_tan` re-uses it to scope the resumed CAMT result.
    # The resume does not re-resolve the SEPAAccount, and the configured IBAN alone can
    # be empty (older Sparkasse accounts without IBAN).
    account_scope: tuple[str, ...] = ()


@dataclass(slots=True)
class FintsCredentials:
    """Connection and login data of an account (PIN in plaintext, in memory only)."""

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
    """Pick a TAN mechanism: the previous one, else decoupled or pushTAN, else the first.

    `mechanisms` is the `{security_function: TwoStepParameters}` mapping from
    `client.get_tan_mechanisms()`.
    """
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
    """Return the account number embedded in a German IBAN, without leading zeros.

    The layout is `DEkk BBBBBBBB KKKKKKKKKK`. The last 10 digits are the account number.
    The result is empty for a non-DE or malformed IBAN, because there is nothing to
    match by.
    """
    return iban[12:22].lstrip("0") if len(iban) == 22 and iban.startswith("DE") else ""


def _norm_kto(value: object) -> str:
    return str(value or "").strip().lstrip("0")


def _select_account(accounts: Sequence[object], iban: str | None):  # type: ignore[no-untyped-def]  # noqa: ANN202
    """Pick the SEPA account that matches the configured `iban`.

    The match runs on the IBAN first. It then compares the account number embedded in
    the German IBAN against the `accountnumber` of the account. That second step exists
    because Sparkasse and others often return SEPA accounts with an EMPTY iban, with
    only KTO and BLZ. With a single account on the login the choice is unambiguous, and
    the function returns that account. With several accounts and no confident match the
    function raises. It never fetches a random account, because that would stage the
    bookings of a FOREIGN account under this one.

    Raises:
        FintsError: The bank returned no SEPA account.
        FintsAccountSelectionError: Several accounts, and none matches with confidence.
    """
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
    """Convert the CAMT documents of an HKCAZ fetch into lines.

    A well-formed document WITHOUT entries counts as 0 lines. That happens on an empty
    day or fetch window, and when the scope filters out all statements.

    `account_ids` scopes each document to the selected account. A combined `camt.053`
    can carry the statements of several accounts.

    Raises:
        StatementParseError: The XML is broken. The client then falls back to MT940.
    """
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
    """Convert a `fints` fetch result into lines, whatever its shape.

    `get_transactions_xml` returns `(booked_xml_docs, pending)`. `get_transactions`
    returns `mt940` transactions, and so does `send_tan` for an MT940 job. `send_tan`
    passes through the result of the ORIGINAL job, so the TAN resume must accept both
    shapes.

    `account_ids` scopes the CAMT path to one account. The MT940 live fetch (HKKAZ) is
    already per account.
    """
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], (list, tuple))
    ):
        booked = [doc for doc in result[0] if isinstance(doc, (bytes, bytearray))]
        return lines_from_camt_documents([bytes(doc) for doc in booked], account_ids)
    return lines_from_mt940_transactions(result)


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
    """Convert the optical TAN challenge (photoTAN or QR-TAN) into a data URL.

    `NeedTANResponse.challenge_matrix` is `(mime: str, data: bytes)` or `None`.

    Returns:
        The data URL, or `None` when the value is malformed or empty. The caller then
        shows the text challenge and the TAN input only.
    """
    matrix = getattr(response, "challenge_matrix", None)
    if not matrix:
        return None
    try:
        mime, data = matrix
    except (TypeError, ValueError):
        return None
    if not data:
        return None
    # Do NOT adopt the bank MIME type blindly. Only known image types go into the data
    # URL, as a defense in depth for the `<img>` binding. Other values get the default.
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
    """Return the identifiers that the fetch is scoped to.

    The scope holds the IBAN AND the account number of the selected SEPA account, which
    is the ground truth of the bank. It also holds the configured account IBAN and the
    number embedded in it. The number is part of the scope because older Sparkasse SEPA
    accounts expose no IBAN. An IBAN-only scope would then be empty and let the bookings
    of every account through. The function matches account numbers with the leading
    zeros stripped, as in the CAMT statement.
    """
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
    """Mask an account identifier for logs: last 4 characters only, never the full IBAN."""
    return f"…{value[-4:]}" if len(value) >= 4 else "…"


def _fetch_lines(
    client: FinTS3PinTanClient, account: object, start: date, account_ids: Collection[str]
) -> object:  # pragma: no cover
    """Fetch transactions: CAMT (HKCAZ) preferred, MT940 (HKKAZ) as fallback.

    `account_ids` scopes the CAMT result to the selected account. A combined `camt.053`
    may carry several accounts.

    Returns:
        The finished lines (`list[StatementLine]`), or the `NeedTANResponse` of the
        fetch.
    """
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
            # Broken CAMT: MT940 is better than no fetch. Do NOT log the contents.
            # They are transaction data. The fallback normalizes on the same path.
            logger.warning("FinTS: camt statements unparseable — falling back to MT940")
    response = client.get_transactions(account, start, end)  # type: ignore[arg-type]
    if isinstance(response, NeedTANResponse):
        return response
    return lines_from_mt940_transactions(response)


def _log_camt_accounts(response: object) -> None:  # pragma: no cover
    """Log which accounts the fetched CAMT contains, with masked ids.

    The log makes a single live run conclusive. It tells an all-accounts fetch apart
    from an empty scope.
    """
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
    """Fetch the accounts and transactions in an open dialog, and catch TAN interrupts."""
    from fints.client import NeedTANResponse

    accounts = client.get_sepa_accounts()
    if isinstance(accounts, NeedTANResponse):
        return _needs_tan(client, accounts, mechanism)
    acct_list = list(accounts)
    # Masked diagnostics with the last 4 characters only: the accounts the bank
    # sent back as IBAN|KTO, and the configured account. This shows a wrong account
    # selection at once.
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
    # Fetch window: from `start_date` (capped by the service) until today.
    start = creds.start_date or date.today()
    scope = _account_scope(account, creds)
    result = _fetch_lines(client, account, start, scope)
    if isinstance(result, NeedTANResponse):
        # Keep the resolved scope for the resume. `submit_tan` parses the result of the
        # paused job without a new selection of the SEPA account.
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
    """Fetch the HKSAL balance as a best effort.

    The function swallows errors and TAN demands. The balance is optional and the
    transactions take precedence.
    """
    from fints.client import NeedTANResponse

    try:
        bal = client.get_balance(account)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - balance is optional, never fail the fetch
        return None
    if isinstance(bal, NeedTANResponse) or bal is None:
        return None
    return balance_from_mt940(bal)


def start_sync(creds: FintsCredentials, *, start_date: date) -> FintsOutcome:  # pragma: no cover
    """Step 1: open the dialog and request the transactions from `start_date`."""
    creds.start_date = start_date
    client = _build_client(creds)
    try:
        # IMPORTANT: fetch the TAN mechanisms over the NETWORK first, with
        # `fetch_tan_mechanisms`. That call populates the BPD, the allowed security
        # functions and the system_id. Plain `get_tan_mechanisms` only reads the BPD.
        # The BPD is EMPTY on a fresh client (`from_data=None`, the case after every
        # credential set) and the call returns `{}`. No two-step mechanism would be
        # chosen and python-fints would sign with a one-step PIN. Sparkassen under PSD2
        # reject that with "9340 invalid signature". The lib misreports it as "wrong
        # PIN", which locks the bank account after 3 attempts.
        from fints.client import NeedTANResponse

        client.fetch_tan_mechanisms()
        mechanisms = client.get_tan_mechanisms()
        mechanism = _pick_tan_mechanism(dict(mechanisms), creds.tan_mechanism)
        # Diagnostic log with NO secrets: the TAN mechanism count and the chosen
        # security function. Empty or None means one-step signing and a Sparkasse
        # "9340". This makes a single live test conclusive without blind retries.
        logger.info(
            "FinTS start_sync: %d TAN mechanism(s) available, selected=%s",
            len(mechanisms),
            mechanism,
        )
        if mechanism:
            client.set_tan_mechanism(mechanism)
        with client:
            # With a fresh `system_id` (after every credential set) the bank demands
            # SCA for the LOGIN itself. python-fints then sets `init_tan_response` at
            # dialog init. Without that confirmation, `get_sepa_accounts` runs on a
            # login that is not strongly authenticated, which gives "9340 invalid
            # signature". So request the login TAN first. `submit_tan` fetches the
            # transactions after the confirmation.
            login_tan = client.init_tan_response
            logger.info(
                "FinTS start_sync: login SCA required=%s", isinstance(login_tan, NeedTANResponse)
            )
            if isinstance(login_tan, NeedTANResponse):
                outcome = _needs_tan(client, login_tan, mechanism, for_login=True)
            else:
                outcome = _fetch(client, creds, mechanism)
        # The dialog is closed now, unless it is paused. Save the persistent state.
        if outcome.status == "done":
            outcome.new_state = client.deconstruct(including_private=True)
        return outcome
    except FintsError:
        raise
    except Exception as exc:  # noqa: BLE001 — wrap lib/network errors uniformly
        # Log the original error on the server ONLY. The text of the lib or the bank
        # can contain request or response fragments, and PIN and TAN are in scope here.
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
        # The `get_data()` and `from_data()` pair of python-fints does NOT round-trip
        # the decoupled flag. `NeedTANResponse._from_data_v1` rebuilds it with
        # `decoupled=False`. The outcome persists the flag in `FintsOutcome.decoupled`,
        # and the code MUST restore it here. Otherwise `send_tan()` takes the
        # non-decoupled branch and submits the empty poll TAN as a normal process-'2'
        # TAN. The bank rejects that with "9xxx", which is misreported as an auth
        # rejection and a lock cooldown on every pushTAN poll.
        if pending.decoupled and isinstance(tan_response, NeedTANResponse):
            tan_response.decoupled = True
        with client.resume_dialog(pending.dialog_data):
            result = client.send_tan(tan_response, tan)
            if isinstance(result, NeedTANResponse):
                # Another TAN is needed, for example a decoupled TAN that is not
                # yet approved. Keep the flag.
                return _needs_tan(
                    client, result, pending.tan_mechanism, for_login=pending.tan_for_login
                )
            if pending.tan_for_login:
                # The login SCA is confirmed. Only NOW fetch the accounts and the
                # transactions. The data step can itself demand a TAN: a data TAN
                # with for_login=False.
                outcome = _fetch(client, creds, pending.tan_mechanism)
                if outcome.status == "done":
                    outcome.new_state = client.deconstruct(including_private=True)
                return outcome
            # `send_tan` returns the result of the paused job: a CAMT tuple or MT940
            # transactions, depending on which fetch demanded the TAN. Scope the CAMT
            # path to the account scope resolved at `start_sync`, because the resume
            # does not re-resolve the selected SEPAAccount. Fall back to the configured
            # IBAN for sessions persisted before the scope existed.
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
