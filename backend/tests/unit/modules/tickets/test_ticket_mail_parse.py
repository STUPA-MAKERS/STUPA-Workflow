"""Unit tests of the mail parser and of the inbox client.

They cover the text of a mail (spec 002728), the identity of a mail (002724), the
automatic mails (002732) and the move to the folder for done mails (002731). The inbox
tests run against a scripted IMAP connection and open no socket.
"""

from __future__ import annotations

import imaplib
from email.message import EmailMessage
from typing import Any

import pytest

from app.modules.tickets.mail_client import MailError
from app.modules.tickets.mail_inbox import Inbox, folder_name
from app.modules.tickets.mail_parse import NO_SUBJECT, html_to_text, parse_mail


def _mail(**headers: str) -> EmailMessage:
    message = EmailMessage()
    for name, value in {"From": "Anna Beispiel <Anna@Example.org>", **headers}.items():
        message[name.replace("_", "-")] = value
    return message


def test_the_text_comes_from_the_plain_part() -> None:
    message = _mail(Subject="Raum", Message_ID="<a1@example.org>")
    message.set_content("Hallo\n\n\n\nWelt")
    message.add_alternative("<p>HTML <b>Teil</b></p>", subtype="html")
    mail = parse_mail(bytes(message))
    assert mail.text == "Hallo\n\nWelt"
    assert mail.identity == "<a1@example.org>"
    assert (mail.sender, mail.sender_name) == ("anna@example.org", "Anna Beispiel")
    assert mail.title == "Raum"
    assert mail.automatic is False


def test_an_html_mail_shows_as_text_without_tags_and_loads_nothing() -> None:
    message = _mail(Subject="Angebot")
    message.set_content(
        "<html><head><style>p{color:red}</style></head><body>"
        "<p>Guten Tag</p><script>fetch('http://t.example/x')</script>"
        '<div>Preis &amp; Termin<img src="http://t.example/pixel.png"></div></body></html>',
        subtype="html",
    )
    text = parse_mail(bytes(message)).text
    assert text == "Guten Tag\n\nPreis & Termin"
    assert "<" not in text
    assert "fetch" not in text
    assert "t.example" not in text


def test_html_to_text_drops_a_script_and_keeps_the_lines() -> None:
    assert html_to_text("<div>Eins</div><br><script>x()</script><div>Zwei</div>") == "Eins\n\nZwei"


def test_a_mail_without_a_message_id_gets_the_hash_of_its_source() -> None:
    message = _mail(Subject="x")
    message.set_content("a")
    source = bytes(message)
    first = parse_mail(source)
    assert first.identity.startswith("sha256:")
    assert parse_mail(source).identity == first.identity
    assert parse_mail(source + b"b").identity != first.identity


def test_a_mail_without_a_subject_gets_the_title_ohne_betreff() -> None:
    message = _mail()
    message.set_content("a")
    assert parse_mail(bytes(message)).title == NO_SUBJECT


def test_the_headers_give_the_parents_the_cc_and_the_number() -> None:
    message = _mail(
        Subject="Re: Raum [T-7K3QX9MD]",
        In_Reply_To="<p@x>",
        References="<q@x> <p@x>",
        Cc="B <b@x.de>, C@x.de",
    )
    message.set_content("a")
    mail = parse_mail(bytes(message))
    assert mail.parents == ("<p@x>", "<q@x>")
    assert mail.cc == ("b@x.de", "c@x.de")
    assert mail.number == "7K3QX9MD"


def test_an_attachment_and_an_inline_image_are_files() -> None:
    message = _mail(Subject="x")
    message.set_content("Text")
    message.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename="a.pdf")
    message.add_attachment(b"\x89PNG", maintype="image", subtype="png")
    files = parse_mail(bytes(message)).files
    assert [(f.name, f.data) for f in files] == [("a.pdf", b"%PDF-1.4"), ("bild-2.png", b"\x89PNG")]


@pytest.mark.parametrize(
    ("headers", "automatic"),
    [
        ({"Auto-Submitted": "auto-replied"}, True),
        ({"Auto-Submitted": "no"}, False),
        ({"Precedence": "bulk"}, True),
        ({"Precedence": "list"}, True),
        ({"Precedence": "junk"}, True),
        ({"Precedence": "first-class"}, False),
        ({"Return-Path": "<>"}, True),
        ({"Return-Path": "<a@example.org>"}, False),
        ({}, False),
    ],
)
def test_a_mail_of_a_machine_is_automatic(headers: dict[str, str], automatic: bool) -> None:
    message = _mail(**headers)
    message.set_content("a")
    assert parse_mail(bytes(message)).automatic is automatic


class _Imap:
    """A scripted IMAP connection that records each command."""

    error = imaplib.IMAP4.error

    def __init__(self, *, capabilities: tuple[str, ...] = ("IMAP4REV1", "MOVE")) -> None:
        self.capabilities = capabilities
        self.commands: list[tuple[Any, ...]] = []
        self.logged_out = False

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        self.commands.append((command, *args))
        match command:
            case "SEARCH":
                return "OK", [b"3 7 5"]
            case "FETCH" if args[1] == "(RFC822.SIZE)":
                return "OK", [b"1 (UID 7 RFC822.SIZE 4242)"]
            case "FETCH":
                return "OK", [(b"1 (UID 7 BODY[] {5}", b"hello"), b")"]
            case _:
                return "OK", [None]

    def create(self, folder: str) -> tuple[str, list[Any]]:
        self.commands.append(("CREATE", folder))
        return "NO", [b"exists"]

    def logout(self) -> None:
        self.logged_out = True


def _inbox(conn: _Imap) -> Inbox:
    return Inbox(conn=conn, uid_validity=1)  # type: ignore[arg-type]


def test_the_inbox_reads_the_uids_above_the_position() -> None:
    conn = _Imap()
    assert _inbox(conn).uids_after(4) == [5, 7]
    assert conn.commands == [("SEARCH", None, "UID 5:*")]


def test_the_inbox_reads_the_size_and_the_source_and_keeps_the_flags() -> None:
    conn = _Imap()
    assert _inbox(conn).size(7) == 4242
    assert _inbox(conn).fetch(7) == b"hello"
    assert conn.commands[-1] == ("FETCH", "7", "(BODY.PEEK[])")


def test_an_imported_mail_moves_to_the_folder_and_is_never_deleted() -> None:
    conn = _Imap()
    _inbox(conn).move(7, "Erledigt")
    assert conn.commands == [("CREATE", '"Erledigt"'), ("MOVE", "7", '"Erledigt"')]
    names = {str(command[0]).upper() for command in conn.commands}
    assert not names & {"STORE", "EXPUNGE", "DELETE", "COPY"}


def test_a_server_without_move_ends_before_a_copy_and_a_delete() -> None:
    conn = _Imap(capabilities=("IMAP4REV1",))
    with pytest.raises(MailError) as caught:
        _inbox(conn).move(7, "Erledigt")
    assert caught.value.code == "move_unsupported"
    assert conn.commands == []


def test_a_folder_name_is_modified_utf7_in_quotes() -> None:
    assert folder_name("Erledigt") == '"Erledigt"'
    assert folder_name("Erledigte Vorgänge & mehr") == '"Erledigte Vorg&AOQ-nge &- mehr"'
    assert folder_name('a"b') == '"a\\"b"'


def test_close_logs_out() -> None:
    conn = _Imap()
    _inbox(conn).close()
    assert conn.logged_out is True
