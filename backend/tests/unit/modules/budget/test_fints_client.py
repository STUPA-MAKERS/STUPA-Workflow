"""FinTS-Client (#fints): reine Logik (TAN-Wahl, Konto-Auswahl). Netz = pragma no cover."""

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
    assert fc._select_account(accs, "de222") is accs[1]  # IBAN-Treffer (normalisiert)


def test_select_account_by_number_when_bank_omits_iban() -> None:
    """Sparkasse: SEPA-Konten OHNE IBAN — Match über die im DE-IBAN steckende KTO."""
    # DE + 2 Prüf + 8 BLZ + 10 KTO. KTO 0001234567 → "1234567".
    iban = "DE00123456780001234567"
    accs = [_Acct("", accountnumber="9999999"), _Acct("", accountnumber="1234567")]
    assert fc._select_account(accs, iban) is accs[1]


def test_select_account_single_returns_it_regardless() -> None:
    only = _Acct("", accountnumber="55")
    assert fc._select_account([only], None) is only
    assert fc._select_account([only], "DE00123456780000000042") is only


def test_select_account_ambiguous_raises() -> None:
    """Mehrere Konten, keiner passt → klarer Fehler statt still falsches Konto."""
    accs = [_Acct("DE111", "1"), _Acct("DE222", "2")]
    with pytest.raises(fc.FintsAccountSelectionError):
        fc._select_account(accs, None)  # keine IBAN konfiguriert
    with pytest.raises(fc.FintsAccountSelectionError):
        fc._select_account(accs, "DE00123456789999999999")  # nichts trifft


def test_select_account_empty_raises() -> None:
    with pytest.raises(fc.FintsError):
        fc._select_account([], None)


def test_select_account_non_de_iban_no_kto_match_raises() -> None:
    """Konfigurierte NICHT-DE-IBAN (kein KTO ableitbar) trifft nichts → klarer Fehler
    statt still falsches Konto (deckt den ``if kto:``-False-Zweig ab)."""
    accs = [_Acct("DE111", "1"), _Acct("DE222", "2")]
    with pytest.raises(fc.FintsAccountSelectionError):
        fc._select_account(accs, "FR761234567890")  # non-DE → kto leer, kein Treffer


def test_kto_from_de_iban() -> None:
    assert fc._kto_from_de_iban("DE00123456780001234567") == "1234567"
    assert fc._kto_from_de_iban("FR761234567890") == ""  # nicht-DE
    assert fc._kto_from_de_iban("DE12") == ""  # zu kurz


def test_account_scope_includes_iban_and_number() -> None:
    """Scope enthält IBAN + KTO (Bank + aus DB-IBAN abgeleitet), führende Nullen weg."""
    acc = _Acct("", accountnumber="0001234567")
    creds = fc.FintsCredentials(
        endpoint="https://x", blz="1", login="u", pin="p",
        account_iban="DE00123456780001234567",
    )
    scope = fc._account_scope(acc, creds)
    assert "DE00123456780001234567" in scope  # konfigurierte IBAN
    assert "1234567" in scope  # KTO (aus Bank-accountnumber + IBAN), Nullen entfernt


def test_account_scope_without_number_or_de_iban() -> None:
    """Bank-Konto ohne accountnumber + NICHT-DE-IBAN als Credential: Scope enthält nur
    die IBAN (deckt die leeren ``_norm_kto``/``_kto_from_de_iban``-Zweige ab)."""
    acc = _Acct("", accountnumber="")  # keine KTO von der Bank
    creds = fc.FintsCredentials(
        endpoint="https://x", blz="1", login="u", pin="p",
        account_iban="FR7612345678901234",  # non-DE → kein KTO ableitbar
    )
    scope = fc._account_scope(acc, creds)
    assert scope == frozenset({fc._norm_iban("FR7612345678901234")})


def test_mask_id_shortens_and_handles_short_values() -> None:
    assert fc._mask_id("DE00123456780001234567") == "…4567"  # letzte 4
    assert fc._mask_id("ab") == "…"  # < 4 Zeichen → nur Maske


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
    assert fc._matrix_data_url(_Resp(None)) is None  # kein optischer Challenge
    assert fc._matrix_data_url(_Resp(("image/png", b""))) is None  # leere Daten
    assert fc._matrix_data_url(object()) is None  # Attribut fehlt


def test_matrix_data_url_bad_tuple() -> None:
    assert fc._matrix_data_url(_Resp(("only-one",))) is None  # nicht entpackbar


def test_matrix_data_url_rejects_unknown_mime() -> None:
    # Bank-gelieferter Nicht-Bild-MIME wird NICHT übernommen → Default image/png (#fints-review).
    url = fc._matrix_data_url(_Resp(("text/html", b"data")))
    assert url is not None and url.startswith("data:image/png;base64,")
    # Erlaubter Typ bleibt erhalten.
    jpg = fc._matrix_data_url(_Resp(("image/jpeg", b"data")))
    assert jpg is not None and jpg.startswith("data:image/jpeg;base64,")


def _global_resolver(_host: str) -> list[str]:
    return ["1.1.1.1"]  # öffentlich → erlaubt


def _internal_resolver(_host: str) -> list[str]:
    return ["10.0.0.5"]  # privat → blockiert


def test_validate_fints_endpoint_ok() -> None:
    # Hostname (DNS gestubbt) + globales IP-Literal.
    fc.validate_fints_endpoint("https://banking.sparkasse.de/fints", resolver=_global_resolver)
    fc.validate_fints_endpoint("https://1.1.1.1/fints", resolver=_global_resolver)


def test_validate_fints_endpoint_rejects() -> None:
    # IP-Literale + Schema/Host brauchen kein DNS.
    for bad in [
        "http://banking.sparkasse.de/fints",   # nicht https
        "https:///fints",                       # kein Host
        "https://127.0.0.1/x",                  # loopback
        "https://169.254.169.254/x",            # link-local (Metadaten)
        "https://10.0.0.5/x",                   # privat
        "https://[::1]/x",                       # IPv6 loopback
    ]:
        with pytest.raises(ValueError):
            fc.validate_fints_endpoint(bad, resolver=_global_resolver)
    # Öffentlicher Name, der auf eine interne IP auflöst → vom DNS-Guard geblockt.
    with pytest.raises(ValueError):
        fc.validate_fints_endpoint("https://evil.example/x", resolver=_internal_resolver)


def test_classify_maps_bank_errors() -> None:
    """Bank-Sperre/Ablehnung → eigene Fehlertypen; alles andere bleibt generisch (#fints-review)."""
    from fints.exceptions import FinTSClientPINError, FinTSClientTemporaryAuthError

    assert isinstance(
        fc._classify(FinTSClientTemporaryAuthError("locked")), fc.FintsBankLockedError
    )
    assert isinstance(
        fc._classify(FinTSClientPINError("rejected")), fc.FintsAuthRejectedError
    )
    generic = fc._classify(RuntimeError("connection refused"))
    assert type(generic) is fc.FintsError  # nicht als Sperre/Ablehnung fehlklassifiziert


def test_classify_walks_exception_chain() -> None:
    """Maskierte Bank-Ablehnung erkennen (#fints-review): python-fints sperrt bei 9340 die PIN,
    der ``with client:``-Teardown wirft dann ``Exception('Refusing to use PIN after block')`` und
    maskiert den ``FinTSClientPINError`` — der muss über ``__context__`` gefunden werden."""
    from fints.exceptions import FinTSClientPINError

    try:
        try:
            raise FinTSClientPINError("PIN wrong?")
        finally:
            raise Exception("Refusing to use PIN after block")  # noqa: B012,TRY002,TRY301
    except Exception as exc:  # noqa: BLE001
        assert isinstance(fc._classify(exc), fc.FintsAuthRejectedError)
