"""Reine Auszählung + Ergebnis-Logik (data-model §5.3, AK »result()-Matrix«).

Zwei seiteneffektfreie Funktionen (keine DB, keine Zeit — voll unit-testbar):

* :func:`tally` — zählt abgegebene Stimmen je Option (``counts``) + ermittelt das
  führende Ergebnis. Nichtzählende Optionen ignoriert.
* :func:`result` — wendet Quorum + Mehrheitsregel an → ``passed | rejected | tie``.

**Entscheidungsmodell (SDS-A3, dokumentierte Annahme, konfigurierbar über die
Options-Konvention).** Die Abstimmung ist eine Ja/Nein-Entscheidung mit optionaler
Enthaltung:

* :data:`YES` (``"yes"``) = Zustimmung, :data:`NO` (``"no"``) = Ablehnung,
  :data:`ABSTAIN` (``"abstain"``) = Enthaltung.
* **Enthaltung** zählt nie zur Mehrheit; sie zählt nur zum **Quorum** und nur, wenn
  ``abstainCountsQuorum`` (Default ``True``).
* Weitere Optionen (n-Options) zählen als abgegebene Stimme (Quorum/Beteiligung),
  fließen aber nicht in die Ja/Nein-Mehrheit ein.

**Mehrheitsregeln** (``yes``/``no`` = Ja/Nein-Stimmen, ``cast`` = alle abgegebenen):

* ``simple``     — Ja > Nein. Patt bei Ja == Nein.
* ``absolute``   — absolute Mehrheit aller abgegebenen Stimmen: ``2·yes > cast``.
  Patt bei ``2·yes == cast`` (keine Seite erreicht die absolute Mehrheit).
* ``two_thirds`` — Zwei-Drittel der Ja/Nein-Stimmen: ``3·yes > 2·(yes+no)``.
  Patt bei exakt zwei Dritteln (``3·yes == 2·(yes+no)``).

Ein **Patt** wird über ``tieBreak`` (``passed | rejected | tie``) aufgelöst; der
Roh-Patt bleibt als ``tie`` erhalten, wenn ``tieBreak == "tie"``. **Verfehltes
Quorum ⇒ ``rejected``** (fail-closed), unabhängig von der Mehrheit.

Ganzzahl-Arithmetik (Vielfache statt Brüche) vermeidet Float-Rundung; das
Prozent-Quorum nutzt :class:`~decimal.Decimal` für exakten Vergleich.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.shared.config_schemas import Quorum, VoteConfig

YES = "yes"
NO = "no"
ABSTAIN = "abstain"

VoteResult = Literal["passed", "rejected", "tie"]


@dataclass(frozen=True, slots=True)
class Outcome:
    """Ergebnis einer Auszählung (rein abgeleitet, kein I/O)."""

    result: VoteResult
    quorum_met: bool
    leading: str | None


def tally(options: Iterable[str], choices: Iterable[str | None]) -> dict[str, int]:
    """Stimmen je **bekannter** Option zählen (unbekannte/NULL-``choice`` ignoriert)."""
    counts = {opt: 0 for opt in options}
    for choice in choices:
        if choice is not None and choice in counts:
            counts[choice] += 1
    return counts


def leading(counts: Mapping[str, int]) -> str | None:
    """Führende Option oder ``None`` (keine Stimmen **oder** Gleichstand an der Spitze)."""
    if not counts:
        return None
    top = max(counts.values())
    if top == 0:
        return None
    winners = [opt for opt, n in counts.items() if n == top]
    return winners[0] if len(winners) == 1 else None


def _quorum_met(quorum: Quorum | None, participation: int, eligible: int) -> bool:
    """Quorum prüfen. ``None`` ⇒ erfüllt. Prozent fail-closed, wenn keine Berechtigten."""
    if quorum is None:
        return True
    value = Decimal(str(quorum.value))
    if quorum.type == "count":
        return Decimal(participation) >= value
    # percent: participation/eligible · 100 ≥ value  →  participation·100 ≥ value·eligible
    if eligible <= 0:
        return False
    return Decimal(participation) * Decimal(100) >= value * Decimal(eligible)


def _majority(rule: str, yes: int, no: int, cast: int) -> VoteResult:
    """Mehrheitsregel auf Ja/Nein anwenden → ``passed | rejected | tie`` (Roh-Patt)."""
    if rule == "absolute":
        threshold = 2 * yes - cast
    elif rule == "two_thirds":
        threshold = 3 * yes - 2 * (yes + no)
    else:  # "simple"
        threshold = yes - no
    if threshold > 0:
        return "passed"
    if threshold < 0:
        return "rejected"
    return "tie"


def _resolve_tie(tie_break: str) -> VoteResult:
    """Roh-Patt über ``tieBreak`` auflösen (``passed | rejected | tie``)."""
    if tie_break == "passed":
        return "passed"
    if tie_break == "rejected":
        return "rejected"
    return "tie"


def result(config: VoteConfig, counts: Mapping[str, int], eligible: int) -> Outcome:
    """Quorum + Mehrheit anwenden → :class:`Outcome` (data-model §5.3)."""
    yes = counts.get(YES, 0)
    no = counts.get(NO, 0)
    abstain = counts.get(ABSTAIN, 0)
    cast = sum(counts.values())

    # Beteiligung fürs Quorum: alle abgegebenen Stimmen, Enthaltungen nur wenn
    # `abstainCountsQuorum` (Default True) — sonst zählen sie nicht zur Beteiligung.
    participation = cast if config.abstain_counts_quorum else cast - abstain
    quorum_met = _quorum_met(config.quorum, participation, eligible)
    lead = leading(counts)

    if not quorum_met:
        return Outcome(result="rejected", quorum_met=False, leading=lead)

    raw = _majority(config.majority_rule, yes, no, cast)
    final: VoteResult = _resolve_tie(config.tie_break) if raw == "tie" else raw
    return Outcome(result=final, quorum_met=True, leading=lead)
