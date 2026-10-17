"""Unit tests of ``app.shared.people``: the wire reference of a person."""

from __future__ import annotations

import uuid

from app.shared.people import DELETED_PERSON, PersonRef, person_of, person_refs
from tests.unit.modules.tickets.fakes import ScriptedSession


def test_person_of_prefers_the_name_then_the_email() -> None:
    pid = uuid.uuid4()
    assert person_of(pid, "Ada", "a@x") == PersonRef(principal_id=pid, display_name="Ada")
    assert person_of(pid, None, "a@x").display_name == "a@x"
    assert person_of(pid, "", None) == DELETED_PERSON


def test_a_reference_serializes_in_camel_case() -> None:
    assert DELETED_PERSON.model_dump(by_alias=True) == {"principalId": None, "displayName": None}


async def test_person_refs_resolves_in_one_query_and_marks_the_missing() -> None:
    known, erased, missing = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    session = ScriptedSession(execute=[[(known, "Ada", None), (erased, None, None)]])
    refs = await person_refs(session, [known, erased, missing, None])  # type: ignore[arg-type]
    assert refs[known].display_name == "Ada"
    assert refs[erased] == DELETED_PERSON
    assert refs[missing] == DELETED_PERSON
    assert len(session.statements) == 1


async def test_person_refs_without_ids_asks_nothing() -> None:
    session = ScriptedSession()
    assert await person_refs(session, [None]) == {}  # type: ignore[arg-type]
    assert session.statements == []
