"""Read the source of a mail into the values that a ticket needs.

``parse_mail`` is pure: it reads bytes and opens no connection. The text of a mail
comes from its plain text part. A mail with only an HTML part gives the text of the
HTML without tags (§F/integrations/ticket-mail/002728): ``script`` and ``style`` blocks
are dropped, and no image or other resource of the mail is loaded, because the parser
never follows an address.

The identity of a mail is its ``Message-ID``. A mail without one gets the SHA-256 of
its source (§F/integrations/ticket-mail/002724).

A mail is automatic (§F/integrations/ticket-mail/002732) with ``Auto-Submitted`` other
than ``no``, with ``Precedence`` ``bulk``, ``list`` or ``junk``, or with an empty return
path.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage, MIMEPart
from email.utils import getaddresses
from html.parser import HTMLParser

from app.modules.tickets.numbers import NUMBER_ALPHABET, NUMBER_LENGTH

#: The title of a ticket from a mail without a subject.
NO_SUBJECT = "Ohne Betreff"
#: The longest title of a ticket.
MAX_TITLE = 200
#: The longest text of a message from a mail.
MAX_TEXT = 100_000
#: The ``Precedence`` values of an automatic mail.
_BULK = frozenset({"bulk", "list", "junk"})
#: The tags whose content is no text of the mail.
_HIDDEN = frozenset({"script", "style", "head", "title"})
#: The tags that end a line.
_BREAKS = frozenset({"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"})
#: The number of a ticket in a subject: ``[T-7K3QX9MD]``.
_NUMBER = re.compile(rf"\[T-([{NUMBER_ALPHABET}]{{{NUMBER_LENGTH}}})\]")
_MESSAGE_ID = re.compile(r"<[^<>\s]+>")
_BLANK_LINES = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t\r\f\v]+")


@dataclass(frozen=True, slots=True)
class MailFile:
    """One attachment or inline image of a mail."""

    name: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ParsedMail:
    """The values of one mail.

    Attributes:
        identity: The ``Message-ID`` with its angle brackets, else ``sha256:<hex>``.
        parents: The ``Message-ID`` values of ``In-Reply-To`` and ``References``.
        sender: The address of ``From``, stripped and lowercase; empty without one.
        sender_name: The display name of ``From``, else empty.
        cc: The addresses of ``Cc``, stripped and lowercase.
        number: The ticket number in the subject without ``T-``, else None.
        automatic: The mail comes from a machine.
    """

    identity: str
    parents: tuple[str, ...]
    subject: str
    sender: str
    sender_name: str
    cc: tuple[str, ...]
    text: str
    files: tuple[MailFile, ...]
    number: str | None
    automatic: bool

    @property
    def title(self) -> str:
        """Return the title of a ticket from this mail."""
        return (self.subject.strip() or NO_SUBJECT)[:MAX_TITLE]


class _TextOfHtml(HTMLParser):
    """Collect the text of an HTML document; drop the tags and the hidden blocks."""

    def __init__(self) -> None:
        """Start with no text and outside each hidden block."""
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Count a hidden block and end the line at a block tag."""
        if tag in _HIDDEN:
            self.hidden = self.hidden + 1
        if tag in _BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """Leave a hidden block and end the line after a block tag."""
        if tag in _HIDDEN and self.hidden:
            self.hidden = self.hidden - 1
        if tag in _BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        """Keep the text outside the hidden blocks."""
        if not self.hidden:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Return the text of an HTML document without a tag."""
    parser = _TextOfHtml()
    parser.feed(html)
    parser.close()
    return _tidy("".join(parser.parts))


def _tidy(text: str) -> str:
    lines = "\n".join(_SPACES.sub(" ", line).strip() for line in text.replace("\r", "").split("\n"))
    return _BLANK_LINES.sub("\n\n", lines).strip()[:MAX_TEXT]


def _content(part: MIMEPart) -> str:
    """Return the text of a part; a part with a broken charset reads with replacements."""
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, ValueError):
        raw = part.get_payload(decode=True)
        return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else ""
    return content if isinstance(content, str) else ""


def _text_of(message: EmailMessage) -> str:
    """Return the plain text of a mail, else the text of its HTML part."""
    plain = message.get_body(preferencelist=("plain",))
    if plain is not None:
        return _tidy(_content(plain))
    html = message.get_body(preferencelist=("html",))
    return html_to_text(_content(html)) if html is not None else ""


def _bytes_of(part: MIMEPart) -> bytes:
    raw = part.get_payload(decode=True)
    return raw if isinstance(raw, bytes) else b""


def _body_parts(message: EmailMessage) -> frozenset[int]:
    """Return the identities of the parts that are the text of the mail."""
    bodies = (
        message.get_body(preferencelist=("plain",)),
        message.get_body(preferencelist=("html",)),
    )
    return frozenset(id(part) for part in bodies if part is not None)


def _files_of(message: EmailMessage) -> tuple[MailFile, ...]:
    """Return each attachment and each inline image of a mail."""
    bodies = _body_parts(message)
    parts = [
        part
        for part in message.walk()
        if isinstance(part, MIMEPart)
        and not part.is_multipart()
        and id(part) not in bodies
        and (part.get_filename() is not None or part.get_content_maintype() == "image")
    ]
    return tuple(
        MailFile(
            name=part.get_filename() or f"bild-{index + 1}.{part.get_content_subtype()}",
            data=_bytes_of(part),
        )
        for index, part in enumerate(parts)
    )


def _ids(*headers: str | None) -> tuple[str, ...]:
    found = [match for header in headers for match in _MESSAGE_ID.findall(header or "")]
    return tuple(dict.fromkeys(found))


def _addresses(*headers: str | None) -> tuple[tuple[str, str], ...]:
    pairs = getaddresses([header for header in headers if header])
    return tuple(
        (name.strip(), address.strip().lower()) for name, address in pairs if "@" in address
    )


def _is_automatic(message: EmailMessage) -> bool:
    auto = str(message.get("Auto-Submitted", "")).strip().lower()
    precedence = str(message.get("Precedence", "")).strip().lower()
    return_path = message.get("Return-Path")
    return (
        (bool(auto) and not auto.startswith("no"))
        or precedence in _BULK
        or (return_path is not None and str(return_path).strip() in {"<>", ""})
    )


def _header(message: EmailMessage, name: str) -> str:
    try:
        return str(message.get(name, "") or "")
    except (LookupError, UnicodeError, ValueError):
        return ""


def parse_mail(source: bytes) -> ParsedMail:
    """Read the source of one mail."""
    message = message_from_bytes(source, policy=policy.default)
    assert isinstance(message, EmailMessage)
    own = _ids(_header(message, "Message-ID"))
    senders = _addresses(_header(message, "From"))
    subject = _SPACES.sub(" ", _header(message, "Subject").replace("\n", " ")).strip()
    number = _NUMBER.search(subject)
    return ParsedMail(
        identity=own[0] if own else f"sha256:{hashlib.sha256(source).hexdigest()}",
        parents=_ids(_header(message, "In-Reply-To"), _header(message, "References")),
        subject=subject,
        sender=senders[0][1] if senders else "",
        sender_name=senders[0][0] if senders else "",
        cc=tuple(dict.fromkeys(address for _name, address in _addresses(_header(message, "Cc")))),
        text=_text_of(message),
        files=_files_of(message),
        number=number.group(1) if number else None,
        automatic=_is_automatic(message),
    )
