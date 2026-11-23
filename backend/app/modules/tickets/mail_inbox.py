"""The inbox of a Postfach: read the new mails and move an imported mail away.

``Inbox`` wraps one logged-in IMAP connection (``mail_client.open_imap``). The standard
library client blocks, so the worker runs each call in a thread.

The platform never deletes a mail on the mail server
(§F/integrations/ticket-mail/002731). An imported mail leaves the inbox with the IMAP
command ``MOVE`` (RFC 6851). A server without ``MOVE`` ends in ``move_unsupported``,
because the other way, a copy with a delete of the first mail, is a delete.

The position in the inbox is the UID of a mail together with the ``UIDVALIDITY`` of the
inbox. A new ``UIDVALIDITY`` means that the server numbered the mails again, so the
caller starts from the first mail.
"""

from __future__ import annotations

import base64
import contextlib
import imaplib
import re
from dataclasses import dataclass

from app.modules.tickets.mail_client import MailAccount, MailError, open_imap

#: The folder of the new mails.
INBOX = "INBOX"
#: The largest source of a mail that the platform reads, in bytes.
MAX_SOURCE_BYTES = 50 * 1024 * 1024
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")
_ASCII_RUN = re.compile(r"[\x20-\x25\x27-\x7e]+|&|[^\x20-\x7e]+")


def _encode_run(run: str) -> str:
    if run == "&":
        return "&-"
    if run.isascii():
        return run
    packed = base64.b64encode(run.encode("utf-16-be")).decode("ascii").rstrip("=")
    return "&" + packed.replace("/", ",") + "-"


def folder_name(name: str) -> str:
    """Return a folder name as an IMAP string: modified UTF-7 (RFC 3501) in quotes."""
    encoded = "".join(_encode_run(run) for run in _ASCII_RUN.findall(name))
    return '"' + encoded.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ok(typ: str) -> None:
    if typ != "OK":
        raise MailError("inbox_failed")


@dataclass(frozen=True, slots=True)
class Inbox:
    """One open inbox.

    Attributes:
        uid_validity: The ``UIDVALIDITY`` of the inbox.
    """

    conn: imaplib.IMAP4
    uid_validity: int

    def uids_after(self, last_uid: int) -> list[int]:
        """Return the UIDs above ``last_uid``, lowest first.

        Raises:
            MailError: ``inbox_failed``.
        """
        try:
            typ, data = self.conn.uid("SEARCH", None, f"UID {last_uid + 1}:*")  # type: ignore[arg-type]
        except imaplib.IMAP4.error:
            raise MailError("inbox_failed") from None
        _ok(typ)
        found = data[0].split() if data and isinstance(data[0], bytes) else []
        return sorted(uid for uid in (int(raw) for raw in found) if uid > last_uid)

    def size(self, uid: int) -> int:
        """Return the size of the source of a mail in bytes.

        Raises:
            MailError: ``inbox_failed``.
        """
        try:
            typ, data = self.conn.uid("FETCH", str(uid), "(RFC822.SIZE)")
        except imaplib.IMAP4.error:
            raise MailError("inbox_failed") from None
        _ok(typ)
        first = data[0] if data else None
        found = _SIZE.search(first) if isinstance(first, bytes) else None
        return int(found.group(1)) if found is not None else 0

    def fetch(self, uid: int) -> bytes:
        """Return the source of a mail and leave its flags as they are.

        Raises:
            MailError: ``inbox_failed``.
        """
        try:
            typ, data = self.conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        except imaplib.IMAP4.error:
            raise MailError("inbox_failed") from None
        _ok(typ)
        first = data[0] if data else None
        if not isinstance(first, tuple) or not isinstance(first[1], bytes):
            raise MailError("inbox_failed")
        return first[1]

    def move(self, uid: int, folder: str) -> None:
        """Move a mail to ``folder``; make the folder when it is missing.

        Raises:
            MailError: ``move_unsupported`` on a server without ``MOVE``, else
                ``move_failed``.
        """
        if "MOVE" not in self.conn.capabilities:
            raise MailError("move_unsupported")
        target = folder_name(folder)
        try:
            self.conn.create(target)
            typ, _data = self.conn.uid("MOVE", str(uid), target)
        except imaplib.IMAP4.error:
            raise MailError("move_failed") from None
        if typ != "OK":
            raise MailError("move_failed")

    def close(self) -> None:
        """Log out; a failure of the logout changes nothing."""
        with contextlib.suppress(Exception):
            self.conn.logout()


def open_inbox(account: MailAccount) -> Inbox:
    """Log in and open the inbox of an account.

    Raises:
        MailError: A cause of ``open_imap``, else ``inbox_failed``.
    """
    conn = open_imap(account)
    try:
        typ, _data = conn.select(INBOX)
        _ok(typ)
        _typ, validity = conn.response("UIDVALIDITY")
    except imaplib.IMAP4.error:
        raise MailError("inbox_failed") from None
    first = validity[0] if validity else None
    return Inbox(conn=conn, uid_validity=int(first) if isinstance(first, bytes) else 0)
