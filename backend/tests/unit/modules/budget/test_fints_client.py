"""FinTS client (#fints): pure logic for the TAN choice and the account choice.

The network path carries `pragma: no cover`.
"""

from __future__ import annotations

import pytest

from app.modules.budget.bank import client as fc


class _Mech:
    def __init__(self, name: str = "", decoupled: bool = False) -> None:
        self.name = name
        self.decoupled = decoupled


class _Acct:
    def __init__(self, iban: str, accountnumber: str = "") -> None:
        self.iban = iban
        self.accountnumber = accountnumber


def test_pick_mechanism_prefers_stored() -> None:
    mechs = {"942": _Mech("chipTAN"), "962": _Mech("pushTAN")}
    assert fc._pick_tan_mechanism(mechs, "942") == "942"


def test_pick_mechanism_prefers_push_decoupled() -> None:
    assert fc._pick_tan_mechanism({"942": _Mech("chipTAN"), "962": _Mech("pushTAN")}, None) == "962"
    assert fc._pick_tan_mechanism({"900": _Mech("x"), "901": _Mech("y", True)}, None) == "901"


def test_pick_mechanism_fallback_first_and_empty() -> None:
    assert fc._pick_tan_mechanism({"942": _Mech("chipTAN")}, None) == "942"
    assert fc._pick_tan_mechanism({}, None) is None


def test_select_account_by_iban() -> None:
    accs = [_Acct("DE111"), _Acct("DE 2 2 2")]
    assert fc._select_account(accs, "de222") is accs[1]  # normalized IBAN match


def test_select_account_by_number_when_bank_omits_iban() -> None:
    """Sparkasse: SEPA accounts carry no IBAN. The match uses the number in the DE IBAN."""
    # DE + 2 check digits + 8 BLZ + 10 account digits. 0001234567 becomes "1234567".
    iban = "DE00123456780001234567"
    accs = [_Acct("", accountnumber="9999999"), _Acct("", accountnumber="1234567")]
    assert fc._select_account(accs, iban) is accs[1]


def test_select_account_single_returns_it_regardless() -> None:
    only = _Acct("", accountnumber="55")
    assert fc._select_account([only], None) is only
    assert fc._select_account([only], "DE00123456780000000042") is only


def test_select_account_ambiguous_raises() -> None:
    """Several accounts and no match give a clear error, not a silently wrong account."""
    accs = [_Acct("DE111", "1"), _Acct("DE222", "2")]
    with pytest.raises(fc.FintsAccountSelectionError):
        fc._select_account(accs, None)  # no IBAN configured
    with pytest.raises(fc.FintsAccountSelectionError):
        fc._select_account(accs, "DE00123456789999999999")  # nothing matches


def test_select_account_empty_raises() -> None:
    with pytest.raises(fc.FintsError):
        fc._select_account([], None)


def test_select_account_non_de_iban_no_kto_match_raises() -> None:
    """A configured non-DE IBAN yields no account number, so nothing matches.

    The code raises a clear error instead of picking a wrong account. This covers the false
    branch of `if kto:`.
    """
    accs = [_Acct("DE111", "1"), _Acct("DE222", "2")]
    with pytest.raises(fc.FintsAccountSelectionError):
        fc._select_account(accs, "FR761234567890")  # non-DE, so kto stays empty


def test_kto_from_de_iban() -> None:
    assert fc._kto_from_de_iban("DE00123456780001234567") == "1234567"
    assert fc._kto_from_de_iban("FR761234567890") == ""  # not DE
    assert fc._kto_from_de_iban("DE12") == ""  # too short


def test_account_scope_includes_iban_and_number() -> None:
    """The scope holds the IBAN and the account number without the leading zeros.

    The account number comes from the bank and from the IBAN in the database.
    """
    acc = _Acct("", accountnumber="0001234567")
    creds = fc.FintsCredentials(
        endpoint="https://x", blz="1", login="u", pin="p",
        account_iban="DE00123456780001234567",
    )
    scope = fc._account_scope(acc, creds)
    assert "DE00123456780001234567" in scope  # configured IBAN
    assert "1234567" in scope  # account number from the bank field and the IBAN, no zeros


def test_account_scope_without_number_or_de_iban() -> None:
    """A bank account without an accountnumber and a non-DE IBAN give a scope with the IBAN.

    This covers the empty branches of `_norm_kto` and `_kto_from_de_iban`.
    """
    acc = _Acct("", accountnumber="")  # no account number from the bank
    creds = fc.FintsCredentials(
        endpoint="https://x", blz="1", login="u", pin="p",
        account_iban="FR7612345678901234",  # non-DE, so no account number
    )
    scope = fc._account_scope(acc, creds)
    assert scope == frozenset({fc._norm_iban("FR7612345678901234")})


def test_mask_id_shortens_and_handles_short_values() -> None:
    assert fc._mask_id("DE00123456780001234567") == "…4567"  # the last 4 characters
    assert fc._mask_id("ab") == "…"  # fewer than 4 characters gives only the mask


def test_outcome_dataclass_defaults() -> None:
    out = fc.FintsOutcome(status="done")
    assert out.lines == []
    assert out.decoupled is False
    assert out.challenge_image is None


class _Resp:
    def __init__(self, matrix: object) -> None:
        self.challenge_matrix = matrix


def test_matrix_data_url_valid() -> None:
    url = fc._matrix_data_url(_Resp(("image/png", b"\x89PNG")))
    assert url is not None
    assert url.startswith("data:image/png;base64,")


def test_matrix_data_url_default_mime() -> None:
    url = fc._matrix_data_url(_Resp((None, b"data")))
    assert url is not None and url.startswith("data:image/png;base64,")


def test_matrix_data_url_absent_or_empty() -> None:
    assert fc._matrix_data_url(_Resp(None)) is None  # no optical challenge
    assert fc._matrix_data_url(_Resp(("image/png", b""))) is None  # empty data
    assert fc._matrix_data_url(object()) is None  # attribute missing


def test_matrix_data_url_bad_tuple() -> None:
    assert fc._matrix_data_url(_Resp(("only-one",))) is None  # not unpackable


def test_matrix_data_url_rejects_unknown_mime() -> None:
    # The code never takes a non-image MIME type from the bank. It falls back to image/png
    # (#fints-review).
    url = fc._matrix_data_url(_Resp(("text/html", b"data")))
    assert url is not None and url.startswith("data:image/png;base64,")
    # An allowed type stays.
    jpg = fc._matrix_data_url(_Resp(("image/jpeg", b"data")))
    assert jpg is not None and jpg.startswith("data:image/jpeg;base64,")


def _global_resolver(_host: str) -> list[str]:
    return ["1.1.1.1"]  # public, so allowed


def _internal_resolver(_host: str) -> list[str]:
    return ["10.0.0.5"]  # private, so blocked


def test_validate_fints_endpoint_ok() -> None:
    # A host name with stubbed DNS and a global IP literal.
    fc.validate_fints_endpoint("https://banking.sparkasse.de/fints", resolver=_global_resolver)
    fc.validate_fints_endpoint("https://1.1.1.1/fints", resolver=_global_resolver)


def test_validate_fints_endpoint_rejects() -> None:
    # IP literals and the scheme or host checks need no DNS.
    for bad in [
        "http://banking.sparkasse.de/fints",   # not https
        "https:///fints",                       # no host
        "https://127.0.0.1/x",                  # loopback
        "https://169.254.169.254/x",            # link-local (metadata)
        "https://10.0.0.5/x",                   # private
        "https://[::1]/x",                       # IPv6 loopback
    ]:
        with pytest.raises(ValueError):
            fc.validate_fints_endpoint(bad, resolver=_global_resolver)
    # The DNS guard blocks a public name that resolves to an internal IP.
    with pytest.raises(ValueError):
        fc.validate_fints_endpoint("https://evil.example/x", resolver=_internal_resolver)


def test_classify_maps_bank_errors() -> None:
    """A bank lock or a rejection maps to its own error type (#fints-review).

    Every other error stays a generic FintsError.
    """
    from fints.exceptions import FinTSClientPINError, FinTSClientTemporaryAuthError

    assert isinstance(
        fc._classify(FinTSClientTemporaryAuthError("locked")), fc.FintsBankLockedError
    )
    assert isinstance(
        fc._classify(FinTSClientPINError("rejected")), fc.FintsAuthRejectedError
    )
    generic = fc._classify(RuntimeError("connection refused"))
    assert type(generic) is fc.FintsError  # not misclassified as a lock or a rejection


def test_classify_walks_exception_chain() -> None:
    """Detect a masked bank rejection (#fints-review).

    On code 9340 python-fints blocks the PIN. The `with client:` teardown then raises
    `Exception("Refusing to use PIN after block")` and masks the `FinTSClientPINError`. The
    classifier must find that error through `__context__`.
    """
    from fints.exceptions import FinTSClientPINError

    try:
        try:
            raise FinTSClientPINError("PIN wrong?")
        finally:
            raise Exception("Refusing to use PIN after block")  # noqa: B012,TRY002,TRY301
    except Exception as exc:  # noqa: BLE001
        assert isinstance(fc._classify(exc), fc.FintsAuthRejectedError)
