"""Test data factories (testing.md §5).

There is one polyfactory builder per domain. This module holds only the cross-cutting
models of the skeleton (`PageParams`). The domain factories (Gremium, application type,
form version, flow version, roles) arrive with the follow-up tasks and inherit from
`BaseFactory`.

`seed_core` is the documented entry point for the seed helper of §5 (Gremium,
application type, form version, flow version and roles). The signature is final. The
implementation follows with the data model (T-06).
"""

from __future__ import annotations

from typing import Any

from polyfactory.factories.pydantic_factory import ModelFactory
from pydantic import BaseModel

from app.shared.paging import PageParams


class BaseFactory[T: BaseModel](ModelFactory[T]):
    """Shared base for all test factories.

    This class does not register itself as a factory. Subclasses build deterministic
    data.
    """

    __is_base_factory__ = True


class PageParamsFactory(BaseFactory[PageParams]):
    __model__ = PageParams


def seed_core(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401 — Platzhalter-Signatur
    """Seed helper stub for the core fixtures (Gremium, type, form, flow, roles).

    The real database seed logic comes with the data model (T-06). The stub exists so
    that follow-up tasks can write against a stable signature.

    Returns:
        A copy of the overrides. No fixture exists yet.
    """
    return dict(overrides)
