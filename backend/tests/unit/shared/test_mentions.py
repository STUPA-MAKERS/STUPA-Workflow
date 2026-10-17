"""Unit tests of the shared mention rules and of the registration of the mention mails."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.admin import principal_merge as merge_mod
from app.modules.admin.principal_merge import PrincipalMergeService, _Tally
from app.modules.notifications import mentions as mails
from app.modules.notifications.kinds import NOTIFICATION_KINDS
from app.modules.notifications.layout import _REASONS, reason_text
from app.modules.notifications.links import ticket_link
from app.modules.notifications.templates_catalogue import CATALOGUE_BY_KEY
from app.modules.notifications.templating import render_mail
from app.modules.todos.merge import MENTION_TABLES, rewrite_mentions
from app.settings import load_settings
from app.shared.errors import ValidationProblem
from app.shared.mentions import (
    MENTION_NOT_MEMBER,
    check_mentions,
    mention_ids,
    new_mentions,
    stored_mentions,
    unique_mentions,
)

A, B, C = (uuid.UUID(int=i) for i in (1, 2, 3))


def test_unique_mentions_keep_the_first_order() -> None:
    assert unique_mentions([B, A, B, C, A]) == [B, A, C]
    assert unique_mentions([]) == []


def test_check_mentions_refuses_an_outsider() -> None:
    check_mentions([], set())
    check_mentions([A, B], {A, B, C})
    with pytest.raises(ValidationProblem) as err:
        check_mentions([A, C], {A, B})
    assert err.value.status == 422
    assert err.value.code == MENTION_NOT_MEMBER
    assert err.value.errors is not None and err.value.errors[0].field == "mentions"


def test_stored_and_parsed_ids_round_trip() -> None:
    assert stored_mentions([A, B]) == [str(A), str(B)]
    assert mention_ids([str(A), "kein-uuid", str(B), 7]) == [A, B]
    assert mention_ids(None) == []


def test_new_mentions_are_the_added_ids() -> None:
    assert new_mentions([C, A, B], [A]) == [C, B]
    assert new_mentions([A], [A, B]) == []


def test_the_mention_kind_and_both_mails_are_registered() -> None:
    assert "mention" in NOTIFICATION_KINDS
    assert "mention" in _REASONS
    assert reason_text("mention", "de") == "Sie erhalten diese E-Mail, weil Sie erwähnt wurden."
    assert reason_text("mention", "en") == (
        "You are receiving this email because you were mentioned."
    )
    for key in ("comment_mentioned", "ticket_mentioned"):
        spec = CATALOGUE_BY_KEY[key]
        assert spec.kind == "mention"
        assert set(spec.subject_i18n) == set(spec.body_i18n) == {"de", "en"}
        assert "link" in spec.placeholders
    assert CATALOGUE_BY_KEY["comment_mentioned"].body_i18n is mails.COMMENT_MENTIONED_BODY
    assert CATALOGUE_BY_KEY["ticket_mentioned"].subject_i18n is mails.TICKET_MENTIONED_SUBJECT


@pytest.mark.parametrize("lang", ["de", "en"])
def test_the_builtins_render_with_their_placeholders(lang: str) -> None:
    comment = render_mail(
        subject_i18n=mails.COMMENT_MENTIONED_SUBJECT,
        body_i18n=mails.COMMENT_MENTIONED_BODY,
        body_html_i18n=mails.COMMENT_MENTIONED_HTML,
        context={
            k: f"<{k}>" for k in mails.COMMENT_MENTIONED_PLACEHOLDERS
        },
        lang=lang,
    )
    assert "<actor>" in comment.subject and "<comment>" in comment.text
    assert comment.html is not None and "&lt;comment&gt;" in comment.html
    note = render_mail(
        subject_i18n=mails.TICKET_MENTIONED_SUBJECT,
        body_i18n=mails.TICKET_MENTIONED_BODY,
        body_html_i18n=mails.TICKET_MENTIONED_HTML,
        context={k: f"<{k}>" for k in mails.TICKET_MENTIONED_PLACEHOLDERS},
        lang=lang,
    )
    assert "<number>" in note.subject and "<message>" in note.text
    assert note.html is not None and "&lt;authorInitials&gt;" in note.html


def test_the_ticket_link_can_open_a_note() -> None:
    settings = load_settings()
    assert ticket_link(settings, "t").url.endswith("/tickets/t")
    assert ticket_link(settings, "t", note_id="n").url.endswith("/tickets/t#note-n")


async def test_rewrite_mentions_refuses_an_unknown_table() -> None:
    assert MENTION_TABLES == ("todo_comment", "comment", "ticket_note")
    with pytest.raises(ValueError, match="no mentions table"):
        await rewrite_mentions(object(), A, B, apply=False, table="principal")  # type: ignore[arg-type]


class _Row:
    def __init__(self, pid: uuid.UUID) -> None:
        self.id = pid


@pytest.mark.parametrize("apply", [False, True])
async def test_the_merge_rewrites_the_chat_mentions(
    monkeypatch: pytest.MonkeyPatch, apply: bool
) -> None:
    calls: list[tuple[str, bool]] = []

    async def _rewrite(_s: Any, old: uuid.UUID, new: uuid.UUID, *, apply: bool, table: str) -> int:
        assert (old, new) == (A, B)
        calls.append((table, apply))
        return {"comment": 2, "ticket_note": 3}[table]

    monkeypatch.setattr(merge_mod, "rewrite_mentions", _rewrite)
    tally = _Tally()
    service = PrincipalMergeService(object())  # type: ignore[arg-type]
    await service._chat_mentions(_Row(A), _Row(B), tally, apply=apply)  # type: ignore[arg-type]
    assert calls == [("comment", apply), ("ticket_note", apply)]
    assert tally.by_area["comments"].rewritten == 2
    assert tally.by_area["tickets"].rewritten == 3
