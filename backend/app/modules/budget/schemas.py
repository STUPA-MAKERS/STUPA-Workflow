"""Geteilte Schema-Basis des Budget-Moduls.

Die alte Flach-Topf-API (``BudgetPot*``/``Assign*``/Stats) wurde durch die
Kostenstellen-Baum-API (:mod:`app.modules.budget.tree_schemas`) abgelöst; übrig
bleibt nur die gemeinsame camelCase-Basisklasse, die die Tree-Schemata erben.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)
