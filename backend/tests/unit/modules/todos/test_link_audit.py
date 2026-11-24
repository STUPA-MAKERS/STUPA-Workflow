"""§F/collaboration/links/002923: the data of a link audit entry."""

from __future__ import annotations

import uuid

from app.modules.auth.principal import Principal
from app.modules.paperless.links import document_ref
from app.modules.todos.link_audit import end_data, link_data
from app.modules.todos.models import Link

CARD = uuid.UUID(int=7)


def test_the_data_names_both_ends_the_number_and_the_grant() -> None:
    link = Link.between(("todo", CARD), ("paperless", document_ref(41)), uuid.UUID(int=1))
    token = Principal(sub="a", grant={"id": "g", "client": "c"})
    data = link_data(link, token)
    assert data["grant"] == {"id": "g", "client": "c"}
    assert sorted([data["a"]["kind"], data["b"]["kind"]]) == ["paperless", "todo"]
    assert end_data("paperless", document_ref(41)) == {
        "kind": "paperless",
        "id": str(document_ref(41)),
        "number": 41,
    }
    assert end_data("todo", CARD) == {"kind": "todo", "id": str(CARD)}
    assert "grant" not in link_data(link, Principal(sub="a"))
