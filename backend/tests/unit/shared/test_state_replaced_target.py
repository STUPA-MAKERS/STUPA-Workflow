"""§ 001722: one terminal, denied state of a flow takes the replaced Anträge."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.shared.config_schemas import FlowGraph, FlowValidationError, StateDef, validate_flow_graph

_DRAFT = {"key": "draft", "label": {"de": "Entwurf"}, "isInitial": True}
_DONE = {"key": "done", "label": {"de": "Erledigt"}, "isTerminal": True}
_REPLACED = {
    "key": "replaced",
    "label": {"de": "Ersetzt"},
    "isTerminal": True,
    "isDenied": True,
    "isReplacedTarget": True,
}


def _graph(*states: dict[str, object]) -> FlowGraph:
    return FlowGraph.model_validate(
        {
            "states": [_DRAFT, _DONE, *states],
            "transitions": [{"from": "draft", "to": "done"}],
        }
    )


def test_the_target_needs_no_transition_into_it() -> None:
    graph = _graph(_REPLACED)
    validate_flow_graph(graph)
    assert [s.key for s in graph.states if s.is_replaced_target] == ["replaced"]
    assert graph.model_dump(by_alias=True)["states"][2]["isReplacedTarget"] is True


def test_an_unreachable_state_still_fails() -> None:
    graph = _graph(_REPLACED, {"key": "lost", "label": {"de": "Verloren"}})
    with pytest.raises(FlowValidationError, match="unreachable"):
        validate_flow_graph(graph)


def test_a_flow_has_at_most_one_target() -> None:
    graph = _graph(_REPLACED, {**_REPLACED, "key": "replaced2"})
    with pytest.raises(FlowValidationError, match="more than one target"):
        validate_flow_graph(graph)


@pytest.mark.parametrize("drop", ["isTerminal", "isDenied"])
def test_the_target_is_terminal_and_denied(drop: str) -> None:
    with pytest.raises(ValidationError, match="terminal and denied"):
        StateDef.model_validate({**_REPLACED, drop: False})
