"""Shared frozen Pydantic bases (§ S/shared/functional/000087).

Every API model is immutable. The class keyword `frozen=True` (not `model_config`) is what
basedpyright reads, so a write to a field of a model is a type error. basedpyright also
requires every subclass to repeat `frozen=True` (`class ItemOut(FrozenCamelModel,
frozen=True)`), so a subclass cannot drop the guarantee by accident. A handler that needs a
changed model builds a new one with `model_copy(update=...)`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel, frozen=True):
    """An immutable Pydantic model."""


class FrozenCamelModel(FrozenModel, frozen=True):
    """An immutable model with camelCase aliases in JSON that also accepts the field names.

    The aliases come from `Field(alias=...)` on each field. `populate_by_name` lets the code
    fill a model by the Python names.
    """

    model_config = ConfigDict(populate_by_name=True)


class FrozenStrictCamelModel(FrozenCamelModel, frozen=True):
    """A `FrozenCamelModel` that rejects unknown fields, for request bodies that must."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
