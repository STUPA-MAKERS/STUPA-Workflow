"""Unit tests of the to-do mails (``todo_assigned``, ``todo_mentioned``, ``todo_due``)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications import todos as mails
from app.modules.notifications.kinds import NOTIFICATION_KINDS
from app.modules.notifications.layout import _REASONS
from app.modules.notifications.links import todo_link
from app.modules.notifications.templates_catalogue import CATALOGUE_BY_KEY
from app.modules.todos.service import TodoMail
from app.settings import load_settings
from tests.unit.modules.todos.fakes import ME, OTHER, ScriptedSession, board, card, column

SETTINGS = load_settings()
KEYS = ("todo_assigned", "todo_mentioned", "todo_due")


class _Maker:
    def __init__(self, *sessions: ScriptedSession) -> None:
        self.sessions = list(sessions)

    def __call__(self) -> _Maker:
        return self

    async def __aenter__(self) -> ScriptedSession:
        return self.sessions.pop(0)

    async def __aexit__(self, *_a: object) -> None:
        return None


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    class _Service:
        def __init__(self, _session: object, **_kw: object) -> None:
            pass

        async def send_kind_mail(self, recipients: list[str], **kw: Any) -> bool:
            out.append({"to": recipients, **kw})
            return True

    monkeypatch.setattr(mails, "NotificationService", _Service)
    return out


def _session(
    *, with_card: bool = True, actor: PrincipalRow | None = None, emails: list[Any] | None = None
) -> tuple[ScriptedSession, Any, Any]:
    b = board(name="StuPa")
    c = card(b, column(b.id), title="Plakat")
    session = ScriptedSession(
        scalars=[emails if emails is not None else ["b@x.org", "a@x.org", None]]
    )
    if with_card:
        session.put(c, b)
    if actor is not None:
        session.put(actor)
    return session, b, c


def test_the_kinds_are_registered() -> None:
    assert set(KEYS) <= set(NOTIFICATION_KINDS)
    assert set(KEYS) <= set(_REASONS)
    for key in KEYS:
        assert set(CATALOGUE_BY_KEY[key].body_i18n) == {"de", "en"}
    link = todo_link(SETTINGS, "c")
    assert link.url.endswith("/todos?card=c")


async def test_the_assigned_mail(sent: list[dict[str, Any]]) -> None:
    actor = PrincipalRow(id=ME, sub="me", display_name="Ada", email="ada@x.org")
    session, b, c = _session(actor=actor)
    mail = TodoMail("assigned", c.id, (OTHER,), ME)
    assert await mails.send_todo_mail(session, queue=None, settings=SETTINGS, mail=mail)  # type: ignore[arg-type]
    (out,) = sent
    assert out["to"] == ["a@x.org", "b@x.org"]
    assert out["kind"] == "todo_assigned"
    assert out["context"] == {"cardTitle": "Plakat", "boardName": "StuPa", "actor": "Ada"}
    assert out["idempotency_parts"] == ("todo_assigned", str(c.id), str(OTHER), str(mail.event_id))
    assert out["link"].url.endswith(f"/todos?card={c.id}")


async def test_two_identical_events_get_two_idempotency_keys(sent: list[dict[str, Any]]) -> None:
    for kind, excerpt in (("assigned", None), ("mentioned", "@B bitte ansehen")):
        for _ in range(2):
            session, _b, c = _session()
            mail = TodoMail(kind, c.id, (OTHER,), ME, excerpt)  # type: ignore[arg-type]
            await mails.send_todo_mail(session, queue=None, settings=SETTINGS, mail=mail)  # type: ignore[arg-type]
    keys = [tuple(out["idempotency_parts"][2:]) for out in sent]
    assert len(sent) == 4
    assert keys[0] != keys[1] and keys[2] != keys[3]


async def test_the_mentioned_mail_and_an_actor_without_a_row(sent: list[dict[str, Any]]) -> None:
    session, _b, c = _session()
    mail = TodoMail("mentioned", c.id, (OTHER,), ME, "Hallo")
    assert await mails.send_todo_mail(session, queue=None, settings=SETTINGS, mail=mail)  # type: ignore[arg-type]
    assert sent[0]["context"]["actor"] == "" and sent[0]["context"]["excerpt"] == "Hallo"
    assert sent[0]["builtin_subject"] is mails.TODO_MENTIONED_SUBJECT
    nameless = PrincipalRow(id=ME, sub="me", display_name=None, email="ada@x.org")
    session, _b, c = _session(actor=nameless)
    mail = TodoMail("mentioned", c.id, (OTHER,), ME)
    await mails.send_todo_mail(session, queue=None, settings=SETTINGS, mail=mail)  # type: ignore[arg-type]
    assert sent[1]["context"]["actor"] == "ada@x.org" and sent[1]["context"]["excerpt"] == ""


async def test_no_mail_without_a_card_or_a_recipient(sent: list[dict[str, Any]]) -> None:
    session, _b, c = _session(with_card=False)
    mail = TodoMail("assigned", c.id, (OTHER,), ME)
    assert not await mails.send_todo_mail(session, queue=None, settings=SETTINGS, mail=mail)  # type: ignore[arg-type]
    orphan = ScriptedSession()
    orphan.put(c)
    assert not await mails.send_todo_mail(orphan, queue=None, settings=SETTINGS, mail=mail)  # type: ignore[arg-type]
    session, _b, c = _session(emails=[])
    mail = TodoMail("assigned", c.id, (OTHER,), ME)
    assert not await mails.send_todo_mail(session, queue=None, settings=SETTINGS, mail=mail)  # type: ignore[arg-type]
    session, _b, c = _session()
    nobody = TodoMail("assigned", c.id, (), ME)
    assert not await mails.send_todo_mail(session, queue=None, settings=SETTINGS, mail=nobody)  # type: ignore[arg-type]
    assert sent == []


async def test_notify_counts_and_survives_a_failure(sent: list[dict[str, Any]]) -> None:
    good, _b, c = _session()
    broken = ScriptedSession()

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("db")

    broken.get = _boom
    empty, _b2, _c2 = _session(emails=[])
    count = await mails.notify_todo_mails(
        queue=None,
        settings=SETTINGS,
        mails=[
            TodoMail("assigned", c.id, (OTHER,), ME),
            TodoMail("assigned", c.id, (OTHER,), ME),
            TodoMail("assigned", _c2.id, (OTHER,), ME),
        ],
        sessionmaker=_Maker(good, broken, empty),  # type: ignore[arg-type]
    )
    assert count == 1


def test_the_default_sessionmaker(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = object()
    monkeypatch.setattr(mails, "get_sessionmaker", lambda: marker)
    assert mails._maker(None) is marker


async def test_the_due_mail(sent: list[dict[str, Any]]) -> None:
    session, b, c = _session()
    due = date(2026, 10, 2)
    assert await mails.send_todo_due(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        card=c,
        board=b,
        assignee_ids=[OTHER],
        due=due,
    )
    assert sent[0]["context"]["dueDate"] == "2026-10-02"
    assert sent[0]["idempotency_parts"] == ("todo_due", str(c.id), "2026-10-02")
    session, b, c = _session(emails=[])
    assert not await mails.send_todo_due(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        card=c,
        board=b,
        assignee_ids=[OTHER],
        due=due,
    )
