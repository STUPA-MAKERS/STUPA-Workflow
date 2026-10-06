"""The merge-aware name lookup (`app.modules.auth.identity`)."""

from __future__ import annotations

import uuid

from app.modules.auth.identity import PrincipalRef, refs_by_id, refs_by_sub
from tests._support.auth_fakes import fake_session, result
from tests._support.identity_rows import id_ref, sub_ref


async def test_empty_input_runs_no_query() -> None:
    db = fake_session()
    assert await refs_by_sub(db, [None, ""]) == {}
    assert await refs_by_id(db, []) == {}


async def test_plain_and_merged_by_sub() -> None:
    plain, target = uuid.uuid4(), uuid.uuid4()
    db = fake_session(
        result(
            sub_ref("a", "Anna", None, plain),
            sub_ref("old", "Alt", "alt@x", merged=(target, None, "neu@x")),
        )
    )
    refs = await refs_by_sub(db, ["a", "old", None])
    assert refs["a"] == PrincipalRef(id=plain, display_name="Anna", email=None, own_name="Anna")
    # A merged account gives the id and the name of the account it was merged into.
    assert refs["old"] == PrincipalRef(
        id=target, display_name=None, email="neu@x", own_name="Alt"
    )
    assert refs["old"].name == "neu@x"
    # A target label names the old account itself.
    assert refs["old"].label == "Alt"
    assert refs["a"].name == "Anna"


async def test_by_id_keys_the_stored_id() -> None:
    old, target = uuid.uuid4(), uuid.uuid4()
    db = fake_session(result(id_ref(old, "Alt", None, merged=(target, "Neu", None))))
    refs = await refs_by_id(db, [old])
    assert refs == {
        old: PrincipalRef(id=target, display_name="Neu", email=None, own_name="Alt")
    }


def test_anonymized_account_has_no_name() -> None:
    assert PrincipalRef(id=uuid.uuid4(), display_name=None, email=None).name is None
    # Without an own name the label falls back to the name of the merge target.
    ref = PrincipalRef(id=uuid.uuid4(), display_name="Neu", email=None)
    assert ref.label == "Neu"
