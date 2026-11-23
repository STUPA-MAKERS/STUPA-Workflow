"""Unit tests of the Postfach of a Bereich and of the mail connections.

They cover the specs 002720, 002743 and 002744 to 002746 with the scripted session and
fake mail servers.
"""

from __future__ import annotations

import ssl
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.audit.actions import AuditAction
from app.modules.tickets import mail_client
from app.modules.tickets import mailbox as mailbox_mod
from app.modules.tickets.mail_client import MailAccount, MailError
from app.modules.tickets.mailbox import TicketMailboxService, host_allowed, mailbox_out
from app.modules.tickets.mailbox_schemas import MailboxCreate, MailboxPatch
from app.modules.tickets.models import TicketArea, TicketMailbox
from app.settings import load_settings
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests.unit.modules.tickets.fakes import ScriptedSession

AREA = uuid.uuid4()
NOW = datetime(2026, 11, 23, tzinfo=UTC)
SETTINGS = load_settings().model_copy(
    update={"ticket_mail_host_allowlist": ["mail.example.org", "smtp.example.org:587"]}
)
SECRETS = ("imap-secret", "smtp-secret")


def _area() -> TicketArea:
    return TicketArea(id=AREA, name="AStA-Büro", platform=False, notify_new=True, in_app=False)


def _row(**kw: Any) -> TicketMailbox:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "area_id": AREA,
        "address": "buero@example.org",
        "imap_host": "mail.example.org",
        "imap_port": 993,
        "imap_user": "buero",
        "imap_password": SECRETS[0],
        "smtp_host": "smtp.example.org",
        "smtp_port": 587,
        "smtp_user": "buero",
        "smtp_password": SECRETS[1],
        "done_folder": "Erledigt",
        "enabled": False,
        "uid_validity": 7,
        "last_uid": 41,
        "failures": 0,
        "last_error": None,
        "fetched_at": None,
    }
    return TicketMailbox(**{**base, **kw})


def _create(**kw: Any) -> MailboxCreate:
    base: dict[str, Any] = {
        "address": "buero@example.org",
        "imapHost": "mail.example.org",
        "imapPort": 993,
        "imapUser": "buero",
        "imapPassword": SECRETS[0],
        "smtpHost": "smtp.example.org",
        "smtpPort": 587,
        "smtpUser": "buero",
        "smtpPassword": SECRETS[1],
    }
    return MailboxCreate.model_validate({**base, **kw})


def _svc(session: ScriptedSession, **kw: Any) -> TicketMailboxService:
    return TicketMailboxService(session, SETTINGS, **kw)  # type: ignore[arg-type]


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    async def _record(_session: object, **kw: Any) -> None:
        out.append(kw)

    monkeypatch.setattr(mailbox_mod, "audit_record", _record)
    return out


# ------------------------------------------------------------------ the service


def test_the_allowlist_takes_a_host_or_a_host_with_its_port() -> None:
    allow = ["Mail.Example.org", " smtp.example.org:587 ", ""]
    assert host_allowed("mail.example.org", 143, allow)
    assert host_allowed("SMTP.example.org", 587, allow)
    assert not host_allowed("smtp.example.org", 465, allow)
    assert not host_allowed("mail.example.org", 993, [])


async def test_create_stores_the_postfach_and_returns_no_password(
    audits: list[dict[str, Any]],
) -> None:
    session = ScriptedSession()
    session.put(_area())
    out = await _svc(session).create(AREA, _create(), "adm")
    (row,) = [o for o in session.added if isinstance(o, TicketMailbox)]
    assert (row.imap_password, row.smtp_password) == SECRETS
    assert (row.done_folder, row.enabled) == ("Erledigt", False)
    dumped = out.model_dump_json(by_alias=True)
    assert "imapHost" in dumped
    assert not any(secret in dumped for secret in SECRETS)
    assert "assword" not in dumped
    (entry,) = audits
    assert entry["action"] is AuditAction.TICKET_MAILBOX
    assert (entry["target_type"], entry["target_id"], entry["actor"]) == (
        "ticket_area",
        str(AREA),
        "adm",
    )
    assert entry["data"]["op"] == "create"
    assert "imapPassword" in entry["data"]["fields"]
    assert not any(secret in str(entry) for secret in SECRETS)
    assert session.committed == 0


async def test_a_second_postfach_of_a_bereich_is_409(audits: list[dict[str, Any]]) -> None:
    session = ScriptedSession(scalar=[_row()])
    session.put(_area())
    with pytest.raises(ConflictError) as exc:
        await _svc(session).create(AREA, _create(), "adm")
    assert exc.value.code == "ticket_mailbox_exists"
    assert audits == []


async def test_a_postfach_of_an_unknown_bereich_is_404() -> None:
    with pytest.raises(NotFoundError):
        await _svc(ScriptedSession()).create(AREA, _create(), "adm")


@pytest.mark.parametrize(
    ("kw", "field"),
    [({"imapHost": "intern.local"}, "imapHost"), ({"smtpPort": 465}, "smtpHost")],
)
async def test_a_host_outside_the_allowlist_is_422(kw: dict[str, Any], field: str) -> None:
    session = ScriptedSession()
    session.put(_area())
    with pytest.raises(ValidationProblem) as exc:
        await _svc(session).create(AREA, _create(**kw), "adm")
    assert exc.value.code == "mail_host_not_allowed"
    assert exc.value.errors is not None
    assert [e.field for e in exc.value.errors] == [field]
    assert session.added == []


async def test_an_empty_allowlist_refuses_each_host() -> None:
    session = ScriptedSession()
    session.put(_area())
    service = TicketMailboxService(
        session,  # type: ignore[arg-type]
        SETTINGS.model_copy(update={"ticket_mail_host_allowlist": []}),
    )
    with pytest.raises(ValidationProblem) as exc:
        await service.create(AREA, _create(), "adm")
    assert exc.value.errors is not None
    assert [e.field for e in exc.value.errors] == ["imapHost", "smtpHost"]


async def test_a_new_password_is_in_the_audit_by_name_only(audits: list[dict[str, Any]]) -> None:
    row = _row(failures=9, last_error="login_failed")
    session = ScriptedSession(scalar=[row])
    out = await _svc(session).patch(
        AREA, MailboxPatch.model_validate({"imapPassword": "neu-geheim"}), "adm"
    )
    assert row.imap_password == "neu-geheim"
    assert row.smtp_password == SECRETS[1]
    assert (row.failures, row.last_error) == (0, None)
    assert (row.uid_validity, row.last_uid) == (7, 41)
    assert out.error is None
    (entry,) = audits
    assert entry["data"] == {
        "op": "update",
        "fields": ["imapPassword"],
        "address": "buero@example.org",
        "enabled": False,
    }
    assert "neu-geheim" not in str(entry)


async def test_the_switch_is_a_change_with_an_audit_entry(audits: list[dict[str, Any]]) -> None:
    row = _row()
    session = ScriptedSession(scalar=[row])
    out = await _svc(session).patch(AREA, MailboxPatch.model_validate({"enabled": True}), "adm")
    assert out.enabled is True
    assert audits[0]["data"]["fields"] == ["enabled"]
    assert audits[0]["data"]["enabled"] is True


async def test_a_new_inbox_starts_the_fetch_from_its_first_mail(
    audits: list[dict[str, Any]],
) -> None:
    row = _row()
    session = ScriptedSession(scalar=[row])
    await _svc(session).patch(AREA, MailboxPatch.model_validate({"imapUser": "office"}), "adm")
    assert (row.uid_validity, row.last_uid) == (None, 0)
    assert audits[0]["data"]["fields"] == ["imapUser"]


async def test_a_patch_without_a_change_writes_no_audit_entry(
    audits: list[dict[str, Any]],
) -> None:
    row = _row(failures=3)
    session = ScriptedSession(scalar=[row])
    await _svc(session).patch(AREA, MailboxPatch.model_validate({"imapPort": 993}), "adm")
    assert row.failures == 3
    assert audits == []


async def test_a_patch_checks_the_hosts_and_needs_a_postfach() -> None:
    session = ScriptedSession(scalar=[_row()])
    with pytest.raises(ValidationProblem):
        await _svc(session).patch(AREA, MailboxPatch.model_validate({"smtpHost": "x.local"}), "adm")
    with pytest.raises(NotFoundError):
        await _svc(ScriptedSession()).patch(AREA, MailboxPatch(), "adm")


async def test_delete_removes_the_postfach_with_an_audit_entry(
    audits: list[dict[str, Any]],
) -> None:
    row = _row()
    session = ScriptedSession(scalar=[row])
    await _svc(session).delete(AREA, "adm")
    assert session.deleted == [row]
    assert audits[0]["data"]["op"] == "delete"
    with pytest.raises(NotFoundError):
        await _svc(ScriptedSession()).delete(AREA, "adm")


async def test_the_listing_names_the_allowed_hosts_and_shows_an_error_after_eight_runs() -> None:
    quiet = _row(failures=7, last_error="timeout")
    loud = _row(area_id=uuid.uuid4(), failures=8, last_error="login_failed", fetched_at=NOW)
    session = ScriptedSession(scalars=[[quiet, loud]])
    listed = await _svc(session).listing()
    assert listed.allowed_hosts == ("mail.example.org", "smtp.example.org:587")
    assert [item.error for item in listed.items] == [None, "login_failed"]
    assert listed.items[1].fetched_at == NOW
    assert mailbox_out(quiet).imap_user == "buero"


async def test_the_test_logs_in_to_both_accounts() -> None:
    seen: list[MailAccount] = []

    def _imap(account: MailAccount) -> str | None:
        seen.append(account)
        return None

    def _smtp(account: MailAccount) -> str | None:
        seen.append(account)
        return "login_failed"

    session = ScriptedSession(scalar=[_row()])
    out = await _svc(session, check_imap=_imap, check_smtp=_smtp).test(AREA)
    assert out.model_dump() == {
        "imap": {"ok": True, "error": None},
        "smtp": {"ok": False, "error": "login_failed"},
    }
    assert sorted((a.host, a.port, a.password) for a in seen) == [
        ("mail.example.org", 993, SECRETS[0]),
        ("smtp.example.org", 587, SECRETS[1]),
    ]
    with pytest.raises(NotFoundError):
        await _svc(ScriptedSession()).test(AREA)


# ------------------------------------------------------------------ the connections


class _Imap:
    """A fake of ``imaplib.IMAP4`` that keeps the order of its calls."""

    calls: list[str]
    capabilities: tuple[str, ...] = ("IMAP4REV1", "STARTTLS")
    error = mail_client.imaplib.IMAP4.error
    fail: Exception | None = None

    def __init__(self, host: str, port: int, **kw: Any) -> None:
        type(self).calls.append(
            f"connect {host}:{port} {'ssl' if 'ssl_context' in kw else 'plain'}"
        )
        self.context = kw.get("ssl_context")

    def starttls(self, context: ssl.SSLContext) -> None:
        type(self).calls.append(f"starttls verify={context.verify_mode == ssl.CERT_REQUIRED}")

    def login(self, user: str, _password: str) -> None:
        type(self).calls.append(f"login {user}")
        if type(self).fail is not None:
            raise type(self).fail

    def shutdown(self) -> None:
        type(self).calls.append("shutdown")

    def logout(self) -> None:
        type(self).calls.append("logout")
        raise OSError("gone")


class _Smtp:
    """A fake of ``smtplib.SMTP``."""

    calls: list[str]
    extensions: tuple[str, ...] = ("starttls",)
    fail: Exception | None = None

    def __init__(self, host: str, port: int, **kw: Any) -> None:
        type(self).calls.append(f"connect {host}:{port} {'ssl' if 'context' in kw else 'plain'}")

    def ehlo(self) -> None:
        type(self).calls.append("ehlo")

    def has_extn(self, name: str) -> bool:
        return name in type(self).extensions

    def starttls(self, *, context: ssl.SSLContext) -> None:
        type(self).calls.append(f"starttls hostname={context.check_hostname}")

    def login(self, user: str, _password: str) -> None:
        type(self).calls.append(f"login {user}")
        if type(self).fail is not None:
            raise type(self).fail

    def close(self) -> None:
        type(self).calls.append("close")

    def quit(self) -> None:
        type(self).calls.append("quit")
        raise OSError("gone")


@pytest.fixture
def servers(monkeypatch: pytest.MonkeyPatch) -> tuple[type[_Imap], type[_Smtp]]:
    imap = type("Imap", (_Imap,), {"calls": []})
    smtp = type("Smtp", (_Smtp,), {"calls": []})
    monkeypatch.setattr(mail_client.imaplib, "IMAP4", imap)
    monkeypatch.setattr(mail_client.imaplib, "IMAP4_SSL", imap)
    monkeypatch.setattr(mail_client.smtplib, "SMTP", smtp)
    monkeypatch.setattr(mail_client.smtplib, "SMTP_SSL", smtp)
    return imap, smtp


def _account(port: int) -> MailAccount:
    return MailAccount("mail.example.org", port, "buero", "geheim")


def test_imap_uses_tls_from_the_start_or_starttls_before_the_login(
    servers: tuple[type[_Imap], type[_Smtp]],
) -> None:
    imap, _smtp = servers
    assert mail_client.check_imap(_account(993)) is None
    assert imap.calls == ["connect mail.example.org:993 ssl", "login buero", "logout"]
    imap.calls.clear()
    assert mail_client.check_imap(_account(143)) is None
    assert imap.calls == [
        "connect mail.example.org:143 plain",
        "starttls verify=True",
        "login buero",
        "logout",
    ]


def test_smtp_uses_tls_from_the_start_or_starttls_before_the_login(
    servers: tuple[type[_Imap], type[_Smtp]],
) -> None:
    _imap, smtp = servers
    assert mail_client.check_smtp(_account(465)) is None
    assert smtp.calls == ["connect mail.example.org:465 ssl", "ehlo", "login buero", "quit"]
    smtp.calls.clear()
    assert mail_client.check_smtp(_account(587)) is None
    assert smtp.calls == [
        "connect mail.example.org:587 plain",
        "ehlo",
        "starttls hostname=True",
        "ehlo",
        "login buero",
        "quit",
    ]


def test_a_server_without_starttls_ends_before_the_login(
    servers: tuple[type[_Imap], type[_Smtp]], monkeypatch: pytest.MonkeyPatch
) -> None:
    imap, smtp = servers
    monkeypatch.setattr(imap, "capabilities", ("IMAP4REV1",))
    monkeypatch.setattr(smtp, "extensions", ())
    assert mail_client.check_imap(_account(143)) == "tls_missing"
    assert mail_client.check_smtp(_account(25)) == "tls_missing"
    assert imap.calls == ["connect mail.example.org:143 plain", "shutdown"]
    assert smtp.calls == ["connect mail.example.org:25 plain", "ehlo", "close"]


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (ssl.SSLError("bad certificate"), "tls_failed"),
        (TimeoutError(), "timeout"),
        (mail_client.imaplib.IMAP4.error("geheim is wrong"), "login_failed"),
        (mail_client.smtplib.SMTPAuthenticationError(535, b"geheim"), "login_failed"),
        (ConnectionRefusedError(), "connect_failed"),
    ],
)
def test_a_failure_is_a_short_cause_without_a_text_of_the_server(
    servers: tuple[type[_Imap], type[_Smtp]],
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    code: str,
) -> None:
    imap, smtp = servers
    monkeypatch.setattr(imap, "fail", exc)
    monkeypatch.setattr(smtp, "fail", exc)
    assert mail_client.check_imap(_account(993)) == code
    assert mail_client.check_smtp(_account(465)) == code
    with pytest.raises(MailError) as raised:
        mail_client.open_imap(_account(993))
    assert str(raised.value) == code
    assert raised.value.__cause__ is None
    assert MailError().code == "connect_failed"


def test_no_oauth_scope_carries_the_postfach_permission() -> None:
    from app.modules.auth import oauth
    from app.modules.auth.principal import Principal
    from app.shared.permissions import PERMISSION_CATALOGUE

    assert "admin.ticket_mail" in PERMISSION_CATALOGUE
    agent = Principal(
        sub="agent",
        roles=["admin"],
        scope_permissions=frozenset(oauth.scope_permissions(list(oauth.SCOPES))),
    )
    assert not agent.has("admin.ticket_mail")
