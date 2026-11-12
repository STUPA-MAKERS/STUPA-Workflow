"""Where the Antrag flow and the Antragsarten use a feature (§F/administration/admin/000761).

A feature in use cannot go off, and a flow or an Antragsart cannot start to use a feature
that is off. Both checks read the same list of uses, so they cannot differ. The functions
are pure: the callers load the flow graph and the Antragsarten.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.modules.site_config.features import Feature
from app.shared.config_schemas import FlowGraph, StateDef, TransitionDef
from app.shared.guards import GREMIUM_SOURCE_BUDGET

UseKind = Literal["state", "transition", "type"]


@dataclass(frozen=True, slots=True)
class FeatureUse:
    """One place that needs a feature: a flow state, a flow transition or an Antragsart."""

    feature: Feature
    kind: UseKind
    name: str

    def as_error(self) -> dict[str, str]:
        """Return the use as a field error: the feature key and ``<kind>:<name>``."""
        return {"field": self.feature.value, "msg": f"{self.kind}:{self.name}"}


def _label(labels: Mapping[str, Any] | None, fallback: str) -> str:
    """Return the German label, then any label, then ``fallback``."""
    texts = labels or {}
    return str(texts.get("de") or next(iter(texts.values()), None) or fallback)


def _state_uses(state: StateDef) -> tuple[FeatureUse, ...]:
    """A vote state starts a vote; its Gremium can come from the Kostenstelle."""
    name = _label(state.label, state.key)
    return (
        ()
        if state.kind != "vote"
        else (
            FeatureUse(Feature.VOTING, "state", name),
            *(
                (FeatureUse(Feature.BUDGET, "state", name),)
                if state.config.get("gremiumSource") == GREMIUM_SOURCE_BUDGET
                else ()
            ),
        )
    )


#: The feature that a transition action needs, by the type of the action.
_ACTION_FEATURE: Mapping[str, Feature] = {
    "addToNextSession": Feature.MEETINGS,
    "assignBudget": Feature.BUDGET,
    "assignBudgetFromMap": Feature.BUDGET,
}


def _transition_uses(
    transition: TransitionDef, labels: Mapping[str, str]
) -> tuple[FeatureUse, ...]:
    """A transition uses the feature of each of its actions, once per feature."""
    name = (
        f"{labels.get(transition.from_, transition.from_)} → "
        f"{labels.get(transition.to, transition.to)}"
    )
    features = frozenset(
        _ACTION_FEATURE[kind]
        for kind in (str(action.get("type")) for action in transition.actions)
        if kind in _ACTION_FEATURE
    )
    return tuple(FeatureUse(f, "transition", name) for f in Feature if f in features)


def flow_uses(graph: FlowGraph | None) -> tuple[FeatureUse, ...]:
    """Return every use of a feature in the flow graph; no graph has no use."""
    states = graph.states if graph is not None else []
    transitions = graph.transitions if graph is not None else []
    labels = {s.key: _label(s.label, s.key) for s in states}
    return (
        *(use for s in states for use in _state_uses(s)),
        *(use for t in transitions for use in _transition_uses(t, labels)),
    )


def type_uses(budget_type_names: Iterable[Mapping[str, Any] | None]) -> tuple[FeatureUse, ...]:
    """Return the use of `Budget` by each Antragsart that has a budget."""
    return tuple(
        FeatureUse(Feature.BUDGET, "type", _label(names, "?")) for names in budget_type_names
    )


def uses_of(uses: Iterable[FeatureUse], features: frozenset[Feature]) -> tuple[FeatureUse, ...]:
    """Return the uses that need one of ``features``."""
    return tuple(use for use in uses if use.feature in features)
