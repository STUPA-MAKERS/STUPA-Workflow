"""Test-Daten-Factories (testing.md §5).

polyfactory-Builder pro Domäne. Hier nur die Querschnitts-Modelle des Skeletts
(`PageParams`); Domänen-Factories (Gremium, AntragsTyp, Form-/Flow-Version, Rollen)
kommen mit den jeweiligen Folge-Tasks dazu und erben von `BaseFactory`.

`seed_core` ist der dokumentierte Einstieg für den Seed-Helper aus §5 (Gremium +
AntragsTyp + Form-Version + Flow-Version + Rollen) — Signatur steht, Implementierung
folgt mit dem Datenmodell (T-06).
"""

from __future__ import annotations

from typing import Any

from polyfactory.factories.pydantic_factory import ModelFactory
from pydantic import BaseModel

from app.shared.paging import PageParams


class BaseFactory[T: BaseModel](ModelFactory[T]):
    """Gemeinsame Basis: nicht selbst registrieren, deterministisch nutzbar."""

    __is_base_factory__ = True


class PageParamsFactory(BaseFactory[PageParams]):
    __model__ = PageParams


def seed_core(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401 — Platzhalter-Signatur
    """Seed-Helper-Stub: Kern-Fixtures (Gremium/Typ/Form/Flow/Rollen).

    Liefert vorerst nur die Overrides zurück; konkrete DB-Seed-Logik kommt mit dem
    Datenmodell (T-06). Existiert hier, damit Folge-Tasks gegen eine stabile Signatur
    schreiben können.
    """
    return dict(overrides)
