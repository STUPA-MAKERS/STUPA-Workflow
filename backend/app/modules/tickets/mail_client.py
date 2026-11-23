"""The connections to the IMAP and the SMTP account of a Postfach.

Each connection uses TLS from the start (IMAP port 993, SMTP port 465) or STARTTLS
before the login, with a checked certificate. A server that offers no STARTTLS ends in
``tls_missing`` before the password goes out (§NF/security/network/002745).

The standard library clients block, so the callers run these functions in a thread
(``asyncio.to_thread``). A failure is a ``MailError`` with a short cause code. The code
never holds a text of the server or a password (§NF/security/network/002746).
"""

from __future__ import annotations

import contextlib
import imaplib
import smtplib
import ssl
from dataclasses import dataclass

#: The port on which an IMAP server talks TLS from the first byte.
IMAP_TLS_PORT = 993
#: The port on which an SMTP server talks TLS from the first byte.
SMTP_TLS_PORT = 465
#: The time limit of one connection in seconds.
TIMEOUT_SECONDS = 10.0


class MailError(Exception):
    """A failed connection to a mail account. ``code`` is the short cause."""

    @property
    def code(self) -> str:
        """The short cause code."""
        return str(self.args[0]) if self.args else "connect_failed"


@dataclass(frozen=True, slots=True)
class MailAccount:
    """The host, the port and the login of one mail account."""

    host: str
    port: int
    user: str
    password: str


def _cause(exc: Exception) -> str:
    """Map an exception of a mail client to a cause code."""
    if isinstance(exc, MailError):
        return exc.code
    if isinstance(exc, ssl.SSLError):
        return "tls_failed"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, imaplib.IMAP4.error | smtplib.SMTPAuthenticationError):
        return "login_failed"
    return "connect_failed"


def _imap_starttls(account: MailAccount, context: ssl.SSLContext, timeout: float) -> imaplib.IMAP4:
    conn = imaplib.IMAP4(account.host, account.port, timeout=timeout)
    if "STARTTLS" not in conn.capabilities:
        conn.shutdown()
        raise MailError("tls_missing")
    conn.starttls(context)
    return conn


def open_imap(account: MailAccount, timeout: float = TIMEOUT_SECONDS) -> imaplib.IMAP4:
    """Open a logged-in IMAP connection through TLS.

    Raises:
        MailError: ``connect_failed``, ``timeout``, ``tls_failed``, ``tls_missing`` or
            ``login_failed``.
    """
    context = ssl.create_default_context()
    try:
        conn = (
            imaplib.IMAP4_SSL(account.host, account.port, ssl_context=context, timeout=timeout)
            if account.port == IMAP_TLS_PORT
            else _imap_starttls(account, context, timeout)
        )
        conn.login(account.user, account.password)
    except Exception as exc:
        raise MailError(_cause(exc)) from None
    return conn


def _smtp_starttls(account: MailAccount, context: ssl.SSLContext, timeout: float) -> smtplib.SMTP:
    conn = smtplib.SMTP(account.host, account.port, timeout=timeout)
    conn.ehlo()
    if not conn.has_extn("starttls"):
        conn.close()
        raise MailError("tls_missing")
    conn.starttls(context=context)
    return conn


def open_smtp(account: MailAccount, timeout: float = TIMEOUT_SECONDS) -> smtplib.SMTP:
    """Open a logged-in SMTP connection through TLS.

    Raises:
        MailError: ``connect_failed``, ``timeout``, ``tls_failed``, ``tls_missing`` or
            ``login_failed``.
    """
    context = ssl.create_default_context()
    try:
        conn = (
            smtplib.SMTP_SSL(account.host, account.port, context=context, timeout=timeout)
            if account.port == SMTP_TLS_PORT
            else _smtp_starttls(account, context, timeout)
        )
        conn.ehlo()
        conn.login(account.user, account.password)
    except Exception as exc:
        raise MailError(_cause(exc)) from None
    return conn


def check_imap(account: MailAccount) -> str | None:
    """Log in to the IMAP account and out again. Return the cause code of a failure."""
    try:
        conn = open_imap(account)
    except MailError as exc:
        return exc.code
    with contextlib.suppress(Exception):
        conn.logout()
    return None


def check_smtp(account: MailAccount) -> str | None:
    """Log in to the SMTP account and out again. Return the cause code of a failure."""
    try:
        conn = open_smtp(account)
    except MailError as exc:
        return exc.code
    with contextlib.suppress(Exception):
        conn.quit()
    return None
