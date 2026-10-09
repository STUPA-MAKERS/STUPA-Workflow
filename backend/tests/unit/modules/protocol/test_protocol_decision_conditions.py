"""Tests of the decision conditions in the protocol (F1)."""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.protocol.markdown import build_vote_snippet
from app.modules.protocol.public import PublicDecision, passed_conditions


def test_snippet_lists_the_conditions() -> None:
    out = build_vote_snippet(
        "T", {"ja": 3, "nein": 1}, question="Q", conditions=["Belege\nnachreichen", "B"]
    )
    lines = out.split("\n")
    assert lines[2] == "> Auflage 1: Belege nachreichen"
    assert lines[3] == "> Auflage 2: B"


def test_snippet_without_conditions_is_unchanged() -> None:
    assert build_vote_snippet("T", None) == "> [!abstimmung] **T**"


def test_passed_conditions_only_for_a_passed_vote() -> None:
    proposal = SimpleNamespace(conditions=["A"])
    assert passed_conditions(SimpleNamespace(result="passed", proposal=proposal)) == ["A"]
    assert passed_conditions(SimpleNamespace(result="rejected", proposal=proposal)) == []
    assert passed_conditions(SimpleNamespace(result="passed", proposal=None)) == []
    assert passed_conditions(SimpleNamespace()) == []


def test_public_decision_carries_the_conditions() -> None:
    view = SimpleNamespace(
        question="Q",
        tally=SimpleNamespace(counts={"ja": 1}),
        result="passed",
        majority_rule="simple",
        secret=False,
        proposal=SimpleNamespace(conditions=["A"]),
    )
    decision = PublicDecision.from_vote(view)
    assert decision.conditions == ["A"]
    assert decision.model_dump(by_alias=True)["conditions"] == ["A"]


def test_old_snapshot_without_conditions_still_loads() -> None:
    decision = PublicDecision.model_validate({"question": "Q", "counts": {}})
    assert decision.conditions == []
