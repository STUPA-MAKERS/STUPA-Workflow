"""Unit tests: the create checks and binds the draft uploads of the wizard (Z4).

The result-queue fake of `test_applications_service_cov` drives the create. The draft
helpers `check_drafts` and `bind_drafts` are faked here; the integration test
`test_create_binds_drafts` runs them against Postgres.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.applications.service import ApplicationsService
from app.modules.applications.service import create as create_mod
from app.shared.errors import ValidationProblem
from tests.unit.modules.applications.test_applications_service_cov import (
    _effective,
    _FakeFlow,
    _FakeForms,
    _ff,
    _Obj,
    _patch_flow,  # noqa: F401 - fixture
    _patch_forms,  # noqa: F401 - fixture
    _payload,
    _reset_flow,  # noqa: F401 - fixture
    _Session,
    _state,
)


class _DraftCalls:
    checked: list[dict[str, Any]] = []
    bound: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _fake_drafts(monkeypatch: pytest.MonkeyPatch) -> type[_DraftCalls]:
    _DraftCalls.checked = []
    _DraftCalls.bound = []

    async def _check(_session: Any, **kw: Any) -> None:  # noqa: ANN401
        _DraftCalls.checked.append(kw)

    async def _bind(_session: Any, **kw: Any) -> None:  # noqa: ANN401
        _DraftCalls.bound.append(kw)

    monkeypatch.setattr(create_mod, "check_drafts", _check)
    monkeypatch.setattr(create_mod, "bind_drafts", _bind)
    return _DraftCalls


def _session_for_create() -> tuple[_Session, UUID]:
    app_type = _Obj(id=uuid4(), has_budget=False, gremium_id=uuid4())
    fv_id = uuid4()
    _FakeForms.effective = _effective(
        [_ff("title", required=True), _ff("belege", type="file")], fv_id
    )
    session = _Session(
        get_results=[app_type],
        execute_results=[[fv_id], [_state(is_initial=True)]],
    )
    return session, fv_id


async def test_create_checks_and_binds_listed_drafts(
    _patch_forms: type[_FakeForms],  # noqa: F811
    _patch_flow: type[_FakeFlow],  # noqa: F811
) -> None:
    session, _ = _session_for_create()
    a, b = uuid4(), uuid4()
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    app, _ = await svc.create(
        _payload(  # type: ignore[arg-type]
            data={"title": "T", "belege": [str(a), str(b)]},
            attachment_ids=[a, b],
            draft_token="tok",
        ),
        draft_pepper="pepper",
    )
    assert _DraftCalls.checked == [
        {"attachment_ids": [a, b], "token": "tok", "pepper": "pepper"}
    ]
    assert _DraftCalls.bound == [
        {"application_id": app.id, "attachment_ids": [a, b], "token": "tok", "pepper": "pepper"}
    ]
    assert session.committed == 1


async def test_create_without_drafts_skips_the_draft_check(
    _patch_forms: type[_FakeForms],  # noqa: F811
    _patch_flow: type[_FakeFlow],  # noqa: F811
) -> None:
    session, _ = _session_for_create()
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    # A free value in a file field stays allowed without drafts (upload after create).
    await svc.create(_payload(data={"title": "T", "belege": "text"}))  # type: ignore[arg-type]
    assert _DraftCalls.checked == []
    assert _DraftCalls.bound == []


async def test_create_with_token_but_no_ids_binds_nothing(
    _patch_forms: type[_FakeForms],  # noqa: F811
    _patch_flow: type[_FakeFlow],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Settings:
        magic_link_secret = "from-settings"

    monkeypatch.setattr(create_mod, "get_settings", lambda: _Settings())
    session, _ = _session_for_create()
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    await svc.create(_payload(data={"title": "T"}, draft_token="tok"))  # type: ignore[arg-type]
    assert _DraftCalls.checked == []
    # Without a pepper from the router the create reads it from the settings.
    assert _DraftCalls.bound[0]["pepper"] == "from-settings"
    assert _DraftCalls.bound[0]["attachment_ids"] == []


async def test_ids_without_token_give_422(
    _patch_forms: type[_FakeForms],  # noqa: F811
) -> None:
    session, _ = _session_for_create()
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem) as caught:
        await svc.create(_payload(data={"title": "T"}, attachment_ids=[uuid4()]))  # type: ignore[arg-type]
    assert caught.value.errors is not None
    assert caught.value.errors[0].field == "draftToken"
    assert session.committed == 0


async def test_file_field_references_must_be_listed(
    _patch_forms: type[_FakeForms],  # noqa: F811
) -> None:
    session, _ = _session_for_create()
    listed, stray = uuid4(), uuid4()
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem) as caught:
        await svc.create(
            _payload(  # type: ignore[arg-type]
                data={"title": "T", "belege": [str(listed), str(stray), "", "frei"]},
                attachment_ids=[listed],
                draft_token="tok",
            ),
            draft_pepper="p",
        )
    assert caught.value.code == "draft_attachments_missing"
    assert caught.value.errors is not None
    assert [e.msg for e in caught.value.errors] == [
        f"{stray} is not in attachmentIds",
        "frei is not in attachmentIds",
    ]
    assert _DraftCalls.checked == []


def test_file_refs_reads_strings_and_lists_of_file_fields_only() -> None:
    fields = [
        _ff("title"),
        _ff("one", type="file"),
        _ff("many", type="file"),
        _ff("none", type="file"),
    ]
    data = {"title": "x", "one": "a", "many": ["b", 3, "c"], "none": None}
    assert list(create_mod._file_refs(fields, data)) == [
        ("one", "a"),
        ("many", "b"),
        ("many", "c"),
    ]


def test_as_uuid() -> None:
    value = uuid4()
    assert create_mod._as_uuid(str(value)) == value
    assert create_mod._as_uuid("nope") is None
