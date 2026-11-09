"""§ 000571: a flow state carries the flags approved and denied, never both, never on a vote."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.shared.config_schemas import FlowGraph, StateDef


def _graph(*states: dict[str, object]) -> FlowGraph:
    return FlowGraph.model_validate(
        {
            "states": [{"key": "draft", "label": {"de": "Entwurf"}, "isInitial": True}, *states],
            "transitions": [],
        }
    )


def test_a_flow_keeps_an_approved_and_a_denied_state() -> None:
    graph = _graph(
        {"key": "ok", "label": {"de": "Bewilligt"}, "isApproved": True},
        {"key": "no", "label": {"de": "Abgelehnt"}, "isDenied": True},
    )
    flags = {s.key: (s.is_approved, s.is_denied) for s in graph.states}
    assert flags == {"draft": (False, False), "ok": (True, False), "no": (False, True)}
    dumped = graph.model_dump(by_alias=True)["states"][1]
    assert dumped["isApproved"] is True
    assert dumped["isDenied"] is False


def test_a_state_refuses_both_flags() -> None:
    with pytest.raises(ValidationError, match="approved and denied"):
        StateDef.model_validate(
            {"key": "x", "label": {"de": "X"}, "isApproved": True, "isDenied": True}
        )


@pytest.mark.parametrize("flag", ["isApproved", "isDenied"])
def test_a_vote_state_refuses_a_flag(flag: str) -> None:
    with pytest.raises(ValidationError, match="vote state"):
        StateDef.model_validate(
            {"key": "v", "label": {"de": "V"}, "kind": "vote", flag: True}
        )
