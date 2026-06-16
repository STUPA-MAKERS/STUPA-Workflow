"""Server-seitige Fuzzy-Suche (#3/#4): Trigram-Ranking auf Postgres, ILIKE-Fallback.

Eine winzige, dialekt-bewusste Hilfe, die aus einer Such-Query ``q`` + einer Liste
durchsuchbarer Spalten/Ausdrücke ein **WHERE**-Prädikat und einen **Rang**-Ausdruck
baut. Beide werden von den Listen-Services identisch in die Zähl- **und** Zeilen-Query
gehängt — so driften ``total`` und Treffer nie auseinander (Infinite-Scroll-Bug).

* **Postgres** (Prod): ``pg_trgm``-Ähnlichkeit. Der Rang ist das Maximum der
  Spalten-Ähnlichkeiten (``greatest(similarity(col, q), …)``); gefiltert wird über
  ``rang > threshold``. Die GIN-Trigram-Indizes (Migration 0027) bedienen ``similarity``.
* **Andere Dialekte** (SQLite in Unit-Stubs): kein ``pg_trgm`` → Substring-``ILIKE``
  über alle Spalten; der Rang ist konstant ``0.0``, damit die Aufrufer **immer**
  ``ORDER BY rang DESC`` schreiben dürfen (auf SQLite ein No-Op-Tiebreak).

``q`` wird **immer** als gebundener Parameter geführt (nie in SQL interpoliert). Die
Aufrufer strippen leere Queries selbst (``if q:``) — diese Hilfe nimmt an, dass ``q``
bereits ein nicht-leerer Suchbegriff ist, strippt aber defensiv erneut.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, func, literal, or_
from sqlalchemy.ext.asyncio import AsyncSession


def escape_like(value: str) -> str:
    """LIKE/ILIKE-Metazeichen (``\\``, ``%``, ``_``) escapen.

    Für die Teilstring-Suche als ``col.ilike(f"%{escape_like(v)}%", escape="\\")``
    nutzen — so wirken vom Nutzer eingegebene ``%``/``_`` als Literale statt als
    Wildcards (kein Index-Bypass / keine Wildcard-Injection durch die Eingabe).
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def dialect_of(session: AsyncSession) -> str:
    """Dialekt-Name der gebundenen Engine (``"postgresql"`` / ``"sqlite"`` / …).

    Steuert in :func:`trigram_rank`, ob ``pg_trgm`` oder der ILIKE-Fallback greift.
    Defensiv: ohne gebundene Engine ``"postgresql"`` (Prod-Default).
    """
    bind = session.bind
    return bind.dialect.name if bind is not None else "postgresql"


def trigram_rank(
    q: str,
    columns: list[Any],
    *,
    threshold: float = 0.3,
    dialect: str = "postgresql",
) -> tuple[ColumnElement[bool], ColumnElement[Any]]:
    """``(where_clause, rank_expr)`` für eine Fuzzy-Suche über ``columns``.

    ``columns`` sind SQLAlchemy-Spalten **oder** -Ausdrücke (z. B. ``func.coalesce``,
    ein Funktionsaufruf auf ``data``). ``q`` ist als Parameter gebunden; ``threshold``
    ist die minimale Wort-Trigram-Ähnlichkeit (Postgres) für einen Treffer.

    Postgres: nutzt ``word_similarity(q, text)`` statt ``similarity`` — letztere
    normalisiert über die GANZE Spalte und kollabiert daher, sobald ein kurzer
    Suchbegriff gegen langen Text (konkatenierte Antworten, Titel + Gremium) läuft;
    ``word_similarity`` misst die beste Übereinstimmung mit einem **Teil**-Wort und
    ist damit das richtige Maß für »kommt die Query im Feld vor«. Rang = Maximum über
    die Spalten, ``where = rang > threshold``. Die GIN-Trigram-Indizes bedienen
    ``word_similarity`` (Operator ``<%``) genauso wie ``similarity``.

    Sonst (SQLite-Stubs): ``where = OR(coalesce(col,'') ILIKE %q%)``, ``rank = 0.0``
    (Konstante; erlaubt bedingungsloses ``ORDER BY rank`` auch im Fallback).
    """
    needle = (q or "").strip()
    if dialect == "postgresql":
        sims = [func.word_similarity(needle, func.coalesce(col, "")) for col in columns]
        rank_expr: ColumnElement[Any] = func.greatest(*sims) if len(sims) > 1 else sims[0]
        where_clause = rank_expr > threshold
        return where_clause, rank_expr
    like = f"%{escape_like(needle)}%"
    where_clause = or_(
        *[func.coalesce(col, "").ilike(like, escape="\\") for col in columns]
    )
    return where_clause, literal(0.0)
