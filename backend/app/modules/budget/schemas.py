"""Shared schema base of the budget module.

The cost-center tree API in `app.modules.budget.tree_schemas` replaced the legacy
flat-pot API. Only the shared camelCase base class remains here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _CamelModel(BaseModel):
    """Use camelCase aliases in JSON and allow population by field name."""

    model_config = ConfigDict(populate_by_name=True)
