"""Pure rules of the status lists.

§ F/administration/admin/003035 the list, § 003036 the phases, § 003037 the dates and
§ 003038 the replacement of a removed status.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.statuses.rules import StatusItem, list_errors, replacement_errors
from app.modules.statuses.schemas import StatusListSet

_GOOD = (
    StatusItem("planned", "open", True),
    StatusItem("ordered", "open", False, "orderedOn"),
    StatusItem("delivered", "done", False, "deliveredOn"),
    StatusItem("cancelled", "void", False),
)


def _msgs(kind: str, items: tuple[StatusItem, ...]) -> list[str]:
    return [error["msg"] for error in list_errors(kind, items)]


def test_a_good_list_has_no_errors() -> None:
    assert list_errors("order", _GOOD) == []
    assert list_errors("event", tuple(StatusItem(i.key, i.phase, i.start) for i in _GOOD)) == []


@pytest.mark.parametrize(
    ("items", "part"),
    [
        ((StatusItem("Planned", "open", True), *_GOOD[1:]), "wrong shape"),
        ((StatusItem("1x", "open", True), *_GOOD[1:]), "wrong shape"),
        ((*_GOOD, StatusItem("planned", "open", False)), "twice"),
        ((StatusItem("planned", "open", False), *_GOOD[1:]), "exactly one"),
        ((*_GOOD, StatusItem("again", "open", True)), "exactly one"),
        ((StatusItem("planned", "done", True), *_GOOD[1:]), "phase open"),
        (_GOOD[:3], "phase void"),
        ((_GOOD[0], _GOOD[3]), "phase done"),
    ],
)
def test_a_wrong_list_names_its_error(items: tuple[StatusItem, ...], part: str) -> None:
    assert any(part in msg for msg in _msgs("order", items))


def test_only_an_order_status_sets_a_date() -> None:
    """§ 003037: the date belongs to the Bestellungen."""
    assert any("only a status of an order" in msg for msg in _msgs("event", _GOOD))


def test_a_replacement_names_a_removed_and_a_kept_key() -> None:
    """§ 003038: the elements of a removed status move to a status of the list."""
    keys = ("planned", "done", "gone")
    assert replacement_errors({"cancelled"}, {"cancelled": "gone"}, keys) == []
    assert replacement_errors({"cancelled"}, {"planned": "gone"}, keys) == [
        {"field": "replacements", "msg": "'planned' is not removed"}
    ]
    assert replacement_errors({"cancelled"}, {"cancelled": "lost"}, keys) == [
        {"field": "replacements", "msg": "'lost' is not in the list"}
    ]


def test_the_body_needs_three_to_thirty_statuses() -> None:
    one = {"key": "a", "name": {"de": "A"}, "phase": "open"}
    with pytest.raises(ValidationError):
        StatusListSet.model_validate({"statuses": [one, one]})
    with pytest.raises(ValidationError):
        StatusListSet.model_validate({"statuses": [one] * 31})
    with pytest.raises(ValidationError):
        StatusListSet.model_validate({"statuses": [{**one, "tone": "pink"}] * 3})
    assert len(StatusListSet.model_validate({"statuses": [one] * 3}).statuses) == 3
