"""Test data factories.

There is one polyfactory builder per domain. This module holds only the cross-cutting
models (`PageParams`). A domain factory inherits from `BaseFactory`.

`seed_core` is the entry point for the seed helper (Gremium, application type, form
version, flow version and roles). It is a stub with a stable signature.
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


def seed_core(**overrides: Any) -> dict[str, Any]:
    """Seed helper stub for the core fixtures (Gremium, type, form, flow, roles).

    The stub gives the tests a stable signature.

    Returns:
        A copy of the overrides.
    """
    return dict(overrides)
