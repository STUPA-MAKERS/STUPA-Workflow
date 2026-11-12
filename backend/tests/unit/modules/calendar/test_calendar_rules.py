"""Unit tests of the pure Termin rules, the mail line of a time span and the mail sender."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

import pytest

from app.modules.calendar import rules
from app.modules.calendar.appointments import AppointmentFacts, AppointmentMail, mine, readable
from app.modules.calendar.mails import notify_appointment_mails, when_text
from app.modules.calendar.router import _deliver_mails, get_appointment_mail_sender
from app.modules.calendar.rules import Span, Targets, Viewer
from app.settings import load_settings

ME, OTHER, GREMIUM = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _span(**kw: object) -> Span:
    base: dict[str, object] = {
        "starts_on": date(2031, 5, 5),
        "ends_on": date(2031, 5, 5),
        "start_time": time(14, 0),
        "end_time": time(16, 0),
        "place": None,
    }
    return Span(**{**base, **kw})  # type: ignore[arg-type]


def test_read_rule() -> None:
    """§F/meetings/calendar/000718: the creator, the invited, everyone with the switch."""
    me = Viewer(id=ME, gremium_ids=frozenset({GREMIUM}))
    assert rules.can_read(me, ME, Targets(), for_all=False)
    assert not rules.can_read(me, OTHER, Targets(), for_all=False)
    assert rules.can_read(me, OTHER, Targets(), for_all=True)
    assert rules.can_read(me, OTHER, Targets(principal_ids=frozenset({ME})), for_all=False)
    assert rules.can_read(me, OTHER, Targets(gremium_ids=frozenset({GREMIUM})), for_all=False)
    assert rules.can_read(Viewer(id=ME, manages=True), OTHER, Targets(), for_all=False)
    assert not rules.can_read(Viewer(id=None, manages=True), None, Targets(), for_all=True)
    assert not rules.is_creator(Viewer(id=None), None)


def test_edit_and_answer_rules() -> None:
    """§F/meetings/calendar/000716: only the creator and a manager change a Termin."""
    me = Viewer(id=ME)
    invited = Targets(principal_ids=frozenset({ME}))
    assert rules.can_edit(me, ME) and not rules.can_edit(me, OTHER)
    assert rules.can_edit(Viewer(id=ME, manages=True), OTHER)
    assert not rules.can_edit(Viewer(id=None, manages=True), None)
    assert rules.sees_answers(me, OTHER, invited) and not rules.sees_answers(me, OTHER, Targets())
    assert rules.sees_answers(me, ME, Targets())
    assert not rules.sees_answers(Viewer(id=None), None, invited)


def test_change_rules() -> None:
    """§F/meetings/calendar/000719: only a moved start or end clears the answers."""
    base = _span()
    assert not rules.time_changed(base, _span(place="Aula"))
    assert rules.needs_mail(base, _span(place="Aula"))
    assert not rules.needs_mail(base, _span(place=""))
    assert rules.time_changed(base, _span(end_time=time(17, 0)))
    assert rules.needs_mail(base, _span(starts_on=date(2031, 5, 4)))


def test_has_ended() -> None:
    """§F/meetings/calendar/000719: an answer is open until the Termin ends."""
    timed = _span()
    assert not rules.has_ended(timed, date(2031, 5, 5), time(15, 59))
    assert rules.has_ended(timed, date(2031, 5, 5), time(16, 0))
    assert rules.has_ended(timed, date(2031, 5, 6), time(0, 0))
    all_day = _span(start_time=None, end_time=None)
    assert not rules.has_ended(all_day, date(2031, 5, 5), time(23, 59))
    assert not rules.has_ended(timed, date(2031, 5, 4), time(23, 59))


def test_forbidden_gremien() -> None:
    """§F/meetings/calendar/000717: only a Gremium whose meetings the creator reads."""
    other = uuid.uuid4()
    assert rules.forbidden_gremien([GREMIUM, other], None, []) == frozenset()
    assert rules.forbidden_gremien([GREMIUM, other], [GREMIUM], []) == {other}
    assert rules.forbidden_gremien([GREMIUM, other], [GREMIUM], [other]) == frozenset()


def test_when_text() -> None:
    assert when_text(_span()) == "05.05.2031 14:00 – 16:00"
    assert when_text(_span(ends_on=date(2031, 5, 6))) == "05.05.2031 14:00 – 06.05.2031 16:00"
    assert when_text(_span(start_time=None, end_time=None)) == "05.05.2031"
    assert (
        when_text(_span(start_time=None, end_time=None, ends_on=date(2031, 5, 7)))
        == "05.05.2031 – 07.05.2031"
    )


def test_sql_conditions_without_a_viewer() -> None:
    """A scoped token has no viewer id and reads no Termin."""
    assert str(readable(Viewer(id=None))) == "false"
    assert str(mine(Viewer(id=None))) == "false"
    assert str(readable(Viewer(id=ME, manages=True))) == "true"


class _Broken:
    def __call__(self) -> object:
        raise RuntimeError("no database")


async def test_mail_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """§F/meetings/calendar/000720: the mails are best effort."""
    settings = load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="session-secret-0123",
        magic_link_secret="magic-link-secret-0",
    )
    mail = AppointmentMail(
        kind="invited",
        facts=AppointmentFacts(
            id=uuid.uuid4(),
            title="T",
            span=_span(),
            description=None,
            sequence=0,
            created_at=datetime(2031, 1, 1, tzinfo=UTC),
        ),
        recipients=(OTHER,),
        actor_id=ME,
    )
    sent = await notify_appointment_mails(
        queue=None,
        settings=settings,
        mails=[mail],
        sessionmaker=_Broken(),  # type: ignore[arg-type]
    )
    assert sent == 0
    seen: list[object] = []

    async def _notify(**kw: object) -> int:
        seen.append(kw["mails"])
        return 0

    monkeypatch.setattr("app.modules.calendar.router.notify_appointment_mails", _notify)
    assert get_appointment_mail_sender() is _deliver_mails
    await _deliver_mails(settings, [mail], None)
    assert seen == [[mail]]
