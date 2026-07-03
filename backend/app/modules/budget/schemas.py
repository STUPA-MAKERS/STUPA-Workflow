"""Shared schema base of the budget module.

The legacy flat-pot API was replaced by the cost-centre tree API
(:mod:`app.modules.budget.tree_schemas`); only the shared camelCase base class
remains.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields populatable by name."""

    model_config = ConfigDict(populate_by_name=True)
