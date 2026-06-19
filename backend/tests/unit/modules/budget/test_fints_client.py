"""FinTS-Client (#fints): reine Logik (TAN-Wahl, Konto-Auswahl). Netz = pragma no cover."""

from __future__ import annotations

import pytest

from app.modules.budget import fints_client as fc


class _Mech:
    def __init__(self, name: str = "", decoupled: bool = False) -> None:
        self.name = name
        self.decoupled = decoupled


class _Acct:
    def __init__(self, iban: str) -> None:
        self.iban = iban


def test_pick_mechanism_prefers_stored() -> None:
    mechs = {"942": _Mech("chipTAN"), "962": _Mech("pushTAN")}
    assert fc._pick_tan_mechanism(mechs, "942") == "942"


def test_pick_mechanism_prefers_push_decoupled() -> None:
    assert fc._pick_tan_mechanism({"942": _Mech("chipTAN"), "962": _Mech("pushTAN")}, None) == "962"
    assert fc._pick_tan_mechanism({"900": _Mech("x"), "901": _Mech("y", True)}, None) == "901"


def test_pick_mechanism_fallback_first_and_empty() -> None:
    assert fc._pick_tan_mechanism({"942": _Mech("chipTAN")}, None) == "942"
    assert fc._pick_tan_mechanism({}, None) is None


def test_select_account_by_iban_then_first() -> None:
    accs = [_Acct("DE111"), _Acct("DE 2 2 2")]
    assert fc._select_account(accs, "de222") is accs[1]  # IBAN-Treffer (normalisiert)
    assert fc._select_account(accs, None) is accs[0]  # ohne IBAN → erstes
    assert fc._select_account(accs, "DE999") is accs[0]  # kein Treffer → erstes


def test_select_account_empty_raises() -> None:
    with pytest.raises(fc.FintsError):
        fc._select_account([], None)


def test_outcome_dataclass_defaults() -> None:
    out = fc.FintsOutcome(status="done")
    assert out.lines == []
    assert out.decoupled is False
