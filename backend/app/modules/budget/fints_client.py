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
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from app.modules.budget.bank_import import StatementLine, lines_from_mt940_transactions
from app.modules.webhooks.ssrf import Resolver, SsrfError, assert_allowed_url, default_resolver

if TYPE_CHECKING:
    from fints.client import FinTS3PinTanClient, NeedTANResponse

logger = logging.getLogger(__name__)


class FintsError(RuntimeError):
    """FinTS-Abruf fehlgeschlagen (Verbindung, Login, Protokoll)."""


class FintsBankLockedError(FintsError):
    """Bank hat den Zugang gesperrt (z. B. nach 3 Fehlversuchen, FinTS-Code 3938).

    **NICHT** automatisch erneut versuchen — jeder weitere Login zählt auf das Bank-
    Fehlversuchskonto ein und kann die Sperre verschärfen, bis sie nur noch von der Bank
    (Hotline/Filiale bzw. Online-Banking-Entsperrung) aufgehoben werden kann (#fints-review)."""


class FintsAuthRejectedError(FintsError):
    """Bank hat Anmeldung/Signatur abgelehnt (FinTS-Codes 9340/9910/9930/9931/9942).

    python-fints meldet diese irreführend als „PIN falsch" und **sperrt danach die PIN-
    Instanz**. Ursache ist oft die Signatur (falsches/fehlendes TAN-Verfahren, fehlende
    Produkt-ID), nicht zwingend die PIN. Vor Wiederholung Ursache klären — sonst droht nach
    wenigen Versuchen die Bank-Sperre (#fints-review)."""


def _classify(exc: BaseException) -> FintsError:
    """Lib-/Bank-Fehler auf unsere Fehlertypen abbilden (Bank-Sperre erkennen, #fints-review).

    **Die ganze Ausnahme-Kette** (``__cause__``/``__context__``) wird durchsucht, NICHT nur die
    äußerste Ausnahme: python-fints sperrt bei 9340 u. a. die PIN-Instanz und der ``with
    client:``-Teardown wirft daraufhin beim Schluss-Signieren ``Exception("Refusing to use PIN
    after block")`` — diese **maskiert** den eigentlichen ``FinTSClientPINError``. Ohne den
    Kettendurchlauf würde die Bank-Ablehnung als generischer 503 statt als 409+Cooldown gemeldet.

    Der Klartext der Lib-/Bank-Meldung wird **nicht** übernommen (kann Request-/Antwort-
    Fragmente bzw. PIN/TAN tragen); nur der Fehler*typ* entscheidet. ``fints`` ist lazy
    importiert, damit der reine Contract-Pfad die Lib nicht braucht."""
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


# Erlaubte MIME-Typen für den optischen TAN-Challenge (photoTAN/QR-TAN als ``<img>``).
_ALLOWED_TAN_IMAGE_MIME = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
)


def validate_fints_endpoint(url: str, *, resolver: Resolver = default_resolver) -> None:
    """FinTS-Endpunkt gegen SSRF prüfen (#fints-review).

    Erzwingt ``https`` (FinTS läuft über TLS) und delegiert die Host-/IP-Prüfung an den
    bestehenden, gehärteten ``assert_allowed_url``-Guard (löst DNS auf, prüft **alle**
    A/AAAA-Records, entpackt IPv4-mapped/6to4/**NAT64** und blockt jede nicht-globale
    Adresse — inkl. loopback/privat/link-local/Metadaten-IP, alternativer IPv4-Kodierungen
    und auf interne IPs auflösender öffentlicher Namen). ``resolver`` ist für Tests
    injizierbar.

    :raises ValueError: Schema ≠ https, oder vom SSRF-Guard abgelehnt.
    """
    if urlsplit(url).scheme.lower() != "https":
        raise ValueError("FinTS endpoint must use https")
    try:
        assert_allowed_url(url, resolver=resolver)
    except SsrfError as exc:
        raise ValueError(f"FinTS endpoint not allowed: {exc}") from exc


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
    # True, wenn die TAN für die **Anmeldung selbst** (SCA bei frischer system_id) gebraucht
    # wird — dann muss ``submit_tan`` nach der TAN-Bestätigung erst noch Konten + Umsätze holen
    # (bei einer Daten-TAN liefert ``send_tan`` die Umsätze direkt). (#fints login-SCA)
    tan_for_login: bool = False


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
    # Den bank-gelieferten MIME-Typ NICHT blind übernehmen — nur bekannte Bild-Typen in die
    # Data-URL lassen (Defense-in-Depth fürs ``<img>``-Binding), sonst Default (#fints-review).
    candidate = str(mime or "").lower().strip()
    mime = candidate if candidate in _ALLOWED_TAN_IMAGE_MIME else "image/png"
    return f"data:{mime};base64,{base64.b64encode(bytes(data)).decode('ascii')}"


def _needs_tan(
    client: FinTS3PinTanClient,
    response: NeedTANResponse,
    mechanism: str | None,
    *,
    for_login: bool = False,
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
        tan_for_login=for_login,
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
        # WICHTIG (#fints-percred): TAN-Verfahren erst über das NETZ holen
        # (``fetch_tan_mechanisms``) — das befüllt BPD + erlaubte Sicherheitsfunktionen +
        # system_id. Das reine ``get_tan_mechanisms`` liest nur aus der bei frischem Client
        # (``from_data=None`` — nach jedem Credential-Setzen der Fall) LEEREN BPD und liefert
        # ``{}`` → es würde KEIN Zwei-Schritt-Verfahren gewählt und python-fints signierte mit
        # Ein-Schritt-PIN. Sparkassen (PSD2) lehnen das mit „9340 Ungültige Signatur" ab — von
        # der Lib irreführend als „PIN falsch" gemeldet, was nach 3 Versuchen die Bank sperrt.
        from fints.client import NeedTANResponse

        client.fetch_tan_mechanisms()
        mechanisms = client.get_tan_mechanisms()
        mechanism = _pick_tan_mechanism(dict(mechanisms), creds.tan_mechanism)
        # Diagnose (#fints, KEINE Geheimnisse): Anzahl TAN-Verfahren + gewählte Sicherheits-
        # funktion. Leer/None ⇒ python-fints signiert Ein-Schritt ⇒ Sparkasse-„9340". So ist
        # ein einziger Live-Test eindeutig auswertbar, ohne blind Fehlversuche zu riskieren.
        logger.info(
            "FinTS start_sync: %d TAN mechanism(s) available, selected=%s",
            len(mechanisms),
            mechanism,
        )
        if mechanism:
            client.set_tan_mechanism(mechanism)
        with client:
            # Bei frischer ``system_id`` (nach jedem Credential-Setzen) verlangt die Bank SCA
            # für die **Anmeldung selbst**: python-fints setzt dann ``init_tan_response`` im
            # Dialog-Init. Ohne diese Bestätigung läuft ``get_sepa_accounts`` auf einer NICHT
            # stark-authentifizierten Anmeldung → „9340 Ungültige Signatur". Also zuerst die
            # Login-TAN anfordern; die Umsätze holt dann ``submit_tan`` nach der Bestätigung.
            login_tan = client.init_tan_response
            logger.info(
                "FinTS start_sync: login SCA required=%s", isinstance(login_tan, NeedTANResponse)
            )
            if isinstance(login_tan, NeedTANResponse):
                outcome = _needs_tan(client, login_tan, mechanism, for_login=True)
            else:
                outcome = _fetch(client, creds, mechanism)
        # Dialog ist (sofern nicht pausiert) zu — persistenten Zustand sichern.
        if outcome.status == "done":
            outcome.new_state = client.deconstruct(including_private=True)
        return outcome
    except FintsError:
        raise
    except Exception as exc:  # noqa: BLE001 — Lib-/Netzfehler einheitlich kapseln
        # Original-Fehler NUR serverseitig loggen — der Lib-/Bank-Text kann Request-/
        # Antwort-Fragmente enthalten und PIN/TAN sind hier im Scope (#fints-review).
        logger.warning("FinTS sync failed", exc_info=exc)
        raise _classify(exc) from exc


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
                # Erneute TAN nötig (z. B. decoupled noch nicht freigegeben) — Flag erhalten.
                return _needs_tan(
                    client, result, pending.tan_mechanism, for_login=pending.tan_for_login
                )
            if pending.tan_for_login:
                # Login-SCA bestätigt → JETZT erst Konten + Umsätze holen (der Daten-Schritt
                # kann seinerseits erneut eine TAN verlangen → dann Daten-TAN, for_login=False).
                outcome = _fetch(client, creds, pending.tan_mechanism)
                if outcome.status == "done":
                    outcome.new_state = client.deconstruct(including_private=True)
                return outcome
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
        logger.warning("FinTS TAN submission failed", exc_info=exc)
        raise _classify(exc) from exc
