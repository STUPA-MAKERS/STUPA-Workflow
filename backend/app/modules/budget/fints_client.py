"""FinTS-Online-Banking-Client (#fints) — Umsatz-Abruf mit PIN/TAN-SCA.

Kapselt die ``fints``-Lib (lazy importiert) hinter zwei Schritten, weil die Starke
Kundenauthentifizierung (PSD2/SCA) eine TAN verlangt, die **zwischen** zwei HTTP-Requests
vom Menschen kommt:

* :func:`start_sync`  — Dialog öffnen, Umsätze anfragen. Liefert entweder die Umsätze
  (``status='done'``) **oder** einen pausierten Dialog-Zustand + TAN-Challenge
  (``status='needs_tan'``), den der Aufrufer persistiert und dem Nutzer zeigt.
* :func:`submit_tan`  — pausierten Dialog fortsetzen und die TAN (oder bei *decoupled*
  pushTAN eine leere TAN zum Pollen) senden. Wieder ``done`` oder erneut ``needs_tan``.

Der **persistente** Client-Zustand (``deconstruct()``: ``system_id`` u. a.) wird nach
erfolgreichem Sync zurückgegeben und vom Service **verschlüsselt** am Konto abgelegt —
das hält das ~90-Tage-SCA-Fenster offen (security.md / #fints-research).

Die Netz-Interaktion ist ohne echte Bank nicht testbar (``# pragma: no cover``); die reine
Logik (TAN-Mechanismus-Wahl, Konto-Auswahl, Umsatz-Normalisierung) bleibt geprüft.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Literal

from app.modules.budget.bank_import import StatementLine, lines_from_mt940_transactions

if TYPE_CHECKING:
    from fints.client import FinTS3PinTanClient, NeedTANResponse


class FintsError(RuntimeError):
    """FinTS-Abruf fehlgeschlagen (Verbindung, Login, Protokoll)."""


@dataclass(slots=True)
class FintsOutcome:
    """Ergebnis eines Sync-Schritts — fertig **oder** TAN benötigt."""

    status: Literal["done", "needs_tan"]
    tan_mechanism: str | None = None
    # status == 'done':
    lines: list[StatementLine] = field(default_factory=list)
    new_state: bytes | None = None  # client.deconstruct() → persistieren
    # status == 'needs_tan' (alle für den Resume nötig):
    client_data: bytes | None = None
    dialog_data: bytes | None = None
    tan_data: bytes | None = None
    challenge: str | None = None
    challenge_html: str | None = None
    # Optischer Challenge (photoTAN/QR-TAN) als fertige Data-URL ``data:<mime>;base64,…``
    # zum direkten Anzeigen im ``<img>`` (#fints-qrtan).
    challenge_image: str | None = None
    decoupled: bool = False


@dataclass(slots=True)
class FintsCredentials:
    """Verbindungs-/Login-Daten eines Kontos (PIN im Klartext, nur im Speicher)."""

    endpoint: str
    blz: str
    login: str
    pin: str
    account_iban: str | None = None
    product_id: str | None = None
    tan_mechanism: str | None = None
    state: bytes | None = None  # zuletzt persistierter Client-Zustand
    start_date: date | None = None  # Abruf-Fenster-Beginn (vom Service gesetzt)


def _pick_tan_mechanism(mechanisms: Mapping[str, object], preferred: str | None) -> str | None:
    """TAN-Mechanismus wählen: zuvor genutzter, sonst *decoupled*/pushTAN, sonst erster.

    ``mechanisms`` = ``{security_function: TwoStepParameters}`` aus
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


def _select_account(accounts: Sequence[object], iban: str | None):  # type: ignore[no-untyped-def]  # noqa: ANN202
    """SEPA-Konto per IBAN wählen (sonst das erste). Leere Liste → ``FintsError``."""
    if not accounts:
        raise FintsError("bank returned no SEPA accounts")
    if iban:
        norm = iban.replace(" ", "").upper()
        for acc in accounts:
            if str(getattr(acc, "iban", "") or "").replace(" ", "").upper() == norm:
                return acc
    return accounts[0]


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
    """Optischen TAN-Challenge (photoTAN/QR-TAN) → Data-URL ``data:<mime>;base64,…``.

    ``NeedTANResponse.challenge_matrix`` ist ``(mime: str, data: bytes)`` oder ``None``;
    fehlerhafte/leere Werte ⇒ ``None`` (dann gibt es nur Text-Challenge + TAN-Eingabe)."""
    matrix = getattr(response, "challenge_matrix", None)
    if not matrix:
        return None
    try:
        mime, data = matrix
    except (TypeError, ValueError):
        return None
    if not data:
        return None
    mime = str(mime or "image/png")
    return f"data:{mime};base64,{base64.b64encode(bytes(data)).decode('ascii')}"


def _needs_tan(
    client: FinTS3PinTanClient, response: NeedTANResponse, mechanism: str | None
) -> FintsOutcome:  # pragma: no cover
    """Dialog pausieren + alles für den späteren Resume einsammeln."""
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
    )


def _fetch(
    client: FinTS3PinTanClient, creds: FintsCredentials, mechanism: str | None
) -> FintsOutcome:  # pragma: no cover
    """Innerhalb eines offenen Dialogs: Konten + Umsätze holen, TAN-Bruch abfangen."""
    from fints.client import NeedTANResponse

    accounts = client.get_sepa_accounts()
    if isinstance(accounts, NeedTANResponse):
        return _needs_tan(client, accounts, mechanism)
    account = _select_account(list(accounts), creds.account_iban)
    # Abruf-Fenster: ab ``start_date`` (vom Service begrenzt) bis heute.
    start = creds.start_date or date.today()
    response = client.get_transactions(account, start, date.today())  # type: ignore[arg-type]
    if isinstance(response, NeedTANResponse):
        return _needs_tan(client, response, mechanism)
    return FintsOutcome(
        status="done",
        tan_mechanism=mechanism,
        lines=lines_from_mt940_transactions(response),
    )


def start_sync(creds: FintsCredentials, *, start_date: date) -> FintsOutcome:  # pragma: no cover
    """Schritt 1: Dialog öffnen und Umsätze ab ``start_date`` anfragen."""
    creds.start_date = start_date
    client = _build_client(creds)
    try:
        mechanisms = client.get_tan_mechanisms()
        mechanism = _pick_tan_mechanism(dict(mechanisms), creds.tan_mechanism)
        if mechanism:
            client.set_tan_mechanism(mechanism)
        with client:
            outcome = _fetch(client, creds, mechanism)
        # Dialog ist (sofern nicht pausiert) zu — persistenten Zustand sichern.
        if outcome.status == "done":
            outcome.new_state = client.deconstruct(including_private=True)
        return outcome
    except FintsError:
        raise
    except Exception as exc:  # noqa: BLE001 — Lib-/Netzfehler einheitlich kapseln
        raise FintsError(f"FinTS sync failed: {exc}") from exc


def submit_tan(  # pragma: no cover
    creds: FintsCredentials, pending: FintsOutcome, tan: str
) -> FintsOutcome:
    """Schritt 2: pausierten Dialog fortsetzen + TAN senden (leer = decoupled-Poll)."""
    from fints.client import NeedRetryResponse, NeedTANResponse

    if pending.client_data is None or pending.dialog_data is None or pending.tan_data is None:
        raise FintsError("incomplete pending-TAN state")
    creds.state = pending.client_data
    client = _build_client(creds)
    try:
        if pending.tan_mechanism:
            client.set_tan_mechanism(pending.tan_mechanism)
        tan_response = NeedRetryResponse.from_data(pending.tan_data)
        with client.resume_dialog(pending.dialog_data):
            result = client.send_tan(tan_response, tan)
            if isinstance(result, NeedTANResponse):
                return _needs_tan(client, result, pending.tan_mechanism)
            lines = lines_from_mt940_transactions(result)
        return FintsOutcome(
            status="done",
            tan_mechanism=pending.tan_mechanism,
            lines=lines,
            new_state=client.deconstruct(including_private=True),
        )
    except FintsError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FintsError(f"FinTS TAN submission failed: {exc}") from exc
