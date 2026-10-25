"""Shared schema base of the budget module.

The cost-center tree API lives in `app.modules.budget.tree_schemas`. This module holds
only the shared camelCase base class.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _CamelModel(BaseModel):
    """Use camelCase aliases in JSON and allow population by field name."""

    model_config = ConfigDict(populate_by_name=True)
