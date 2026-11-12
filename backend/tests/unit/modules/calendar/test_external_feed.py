"""Unit tests of the reader of an external ICS feed (specs 000722, 000723)."""

from __future__ import annotations

from datetime import date, time

import pytest

from app.modules.calendar.external_feed import MAX_ENTRIES, FeedError, parse_feed, plain

TODAY = date(2026, 11, 11)


def _feed(*events: str) -> bytes:
    body = "\n".join(f"BEGIN:VEVENT\n{event.strip()}\nEND:VEVENT" for event in events)
    return f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:test\n{body}\nEND:VCALENDAR\n".encode()


def test_plain_text_without_addresses() -> None:
    """§F/meetings/calendar/000723: plain text, no organiser, no attendee."""
    entries = parse_feed(
        _feed(
            """
UID:a
DTSTART;TZID=Europe/Berlin:20261105T180000
DTEND;TZID=Europe/Berlin:20261105T193000
SUMMARY:<b>Chor</b> &amp; Band
ORGANIZER;CN=Olga:mailto:olga@example.org
ATTENDEE;CN=Paul:mailto:paul@example.org
LOCATION:<i>Aula</i>
DESCRIPTION:<p>Probe</p>\\n\\n\\n\\n  im   Keller
"""
        ),
        TODAY,
    )
    assert len(entries) == 1
    entry = entries[0]
    assert (entry.title, entry.place, entry.description) == (
        "Chor & Band",
        "Aula",
        "Probe\n\nim Keller",
    )
    assert (entry.starts_on, entry.start_time, entry.end_time) == (
        date(2026, 11, 5),
        time(18, 0),
        time(19, 30),
    )
    assert "example.org" not in repr(entry)


def test_weekly_entry_shows_on_each_date() -> None:
    """§F/meetings/calendar/000723: a weekly entry, without its excluded and moved dates."""
    entries = parse_feed(
        _feed(
            """
UID:a
DTSTART;TZID=Europe/Berlin:20261005T180000
DTEND;TZID=Europe/Berlin:20261005T190000
RRULE:FREQ=WEEKLY;UNTIL=20261102T170000Z
EXDATE;TZID=Europe/Berlin:20261012T180000
SUMMARY:Chor
""",
            """
UID:a
RECURRENCE-ID;TZID=Europe/Berlin:20261019T180000
DTSTART;TZID=Europe/Berlin:20261020T190000
DTEND;TZID=Europe/Berlin:20261020T200000
SUMMARY:Chor verlegt
""",
        ),
        TODAY,
    )
    assert [(e.starts_on, e.start_time, e.title) for e in entries] == [
        (date(2026, 10, 5), time(18, 0), "Chor"),
        (date(2026, 10, 20), time(19, 0), "Chor verlegt"),
        (date(2026, 10, 26), time(18, 0), "Chor"),
        (date(2026, 11, 2), time(18, 0), "Chor"),
    ]


def test_series_keeps_the_local_time_and_the_window() -> None:
    """A daily series stays at its local time and ends 24 months ahead."""
    entries = parse_feed(
        _feed("UID:a\nDTSTART;TZID=Europe/Berlin:20200101T090000\nRRULE:FREQ=MONTHLY\nSUMMARY:M"),
        TODAY,
    )
    assert entries[0].starts_on == date(2025, 12, 1)
    assert entries[-1].starts_on == date(2028, 11, 1)
    assert {e.start_time for e in entries} == {time(9, 0)}


def test_all_day_span_and_utc_time() -> None:
    entries = parse_feed(
        _feed(
            "UID:b\nDTSTART;VALUE=DATE:20261224\nDTEND;VALUE=DATE:20261227\nSUMMARY:Ferien",
            "UID:c\nDTSTART:20261101T100000Z\nDURATION:PT90M\nSUMMARY:UTC",
            "UID:d\nDTSTART;VALUE=DATE:20261201\nSUMMARY:Ein Tag",
            "UID:e\nDTSTART:20261202T080000\nDTEND:20261201T080000\nSUMMARY:Ende davor",
        ),
        TODAY,
    )
    by_title = {e.title: e for e in entries}
    assert (by_title["Ferien"].starts_on, by_title["Ferien"].ends_on) == (
        date(2026, 12, 24),
        date(2026, 12, 26),
    )
    assert by_title["Ferien"].start_time is None
    assert (by_title["UTC"].start_time, by_title["UTC"].end_time) == (time(11, 0), time(12, 30))
    assert by_title["Ein Tag"].ends_on == date(2026, 12, 1)
    assert by_title["Ende davor"].end_time == time(8, 0)


@pytest.mark.parametrize(
    "rule",
    ["FREQ=MINUTELY", "FREQ=WEEKLY;UNTIL=20261301T000000Z", "INTERVAL=2", "FREQ=WEEKLY;INTERVAL=0"],
)
def test_fast_or_broken_rule_gives_the_first_date(rule: str) -> None:
    entries = parse_feed(
        _feed(
            f"UID:a\nDTSTART:20261105T100000Z\nRRULE:{rule}\nEXDATE:kaputt\nSUMMARY:Takt"
        ),
        TODAY,
    )
    assert [e.starts_on for e in entries] == [date(2026, 11, 5)]


def test_event_without_start_or_title_is_skipped() -> None:
    entries = parse_feed(
        _feed(
            "UID:a\nSUMMARY:Ohne Start",
            "UID:b\nDTSTART:20261105T100000Z\nSUMMARY:<br>",
            "UID:c\nDTSTART:kaputt\nSUMMARY:Kaputt",
            "UID:d\nDTSTART;VALUE=DATE:20261105\nSUMMARY:Gut",
        ),
        TODAY,
    )
    assert [e.title for e in entries] == ["Gut"]


def test_keeps_the_entries_nearest_to_today() -> None:
    events = [
        f"UID:u{i}\nDTSTART;VALUE=DATE:20261111\nRRULE:FREQ=DAILY;COUNT=700\nSUMMARY:T{i}"
        for i in range(8)
    ]
    entries = parse_feed(_feed(*events), TODAY)
    assert len(entries) == MAX_ENTRIES
    assert entries[0].starts_on == TODAY


@pytest.mark.parametrize("data", [b"", b"<html>login</html>", b"BEGIN:VCALENDAR\nBEGIN:VEVENT\n"])
def test_not_a_calendar(data: bytes) -> None:
    with pytest.raises(FeedError):
        parse_feed(data, TODAY)


def test_plain_limits_and_empties() -> None:
    assert plain(None, 10) is None
    assert plain("<p> </p>", 10) is None
    assert plain("abcdef", 3) == "abc"
