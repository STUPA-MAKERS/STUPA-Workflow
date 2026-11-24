"""Integration: the secrets of the integrations rest sealed (§NF/security/integrity/002810).

The first test writes each secret through the ORM and reads the raw column. The second test
goes back before the migration ``80d82c7f078d``, stores plain rows, upgrades and expects
sealed rows that open to the old values.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.modules.auth.models import Principal
from app.modules.notifications.push_models import PushVapidKey
from app.modules.paperless.models import PaperlessSettings
from app.modules.tickets.models import TicketArea, TicketMailbox
from app.modules.webhooks.models import Webhook
from app.shared.sealed import is_sealed

pytestmark = pytest.mark.integration

_BEFORE = "e0dd72d776c9"
_TOKEN = "kalender-token-0123456789"


def _clean(eng: Engine) -> None:
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM ticket_area WHERE name IN ('Sealed', 'Alt')"))
        for table in ("webhook", "push_vapid_key", "paperless_settings"):
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("DELETE FROM principal WHERE sub LIKE 'sealed-%'"))


@pytest.fixture
def eng(engine: Engine) -> Iterator[Engine]:
    _clean(engine)
    try:
        yield engine
    finally:
        _clean(engine)


def _raw(eng: Engine) -> dict[str, str]:
    with eng.connect() as conn:
        box = conn.execute(text("SELECT imap_password, smtp_password FROM ticket_mailbox")).one()
        return {
            "imap": box[0],
            "smtp": box[1],
            "paperless": conn.execute(text("SELECT token FROM paperless_settings")).scalar_one(),
            "vapid": conn.execute(text("SELECT private_pem FROM push_vapid_key")).scalar_one(),
            "calendar": conn.execute(
                text("SELECT calendar_token FROM principal WHERE sub LIKE 'sealed-%'")
            ).scalar_one(),
            "webhook": conn.execute(text("SELECT secret::text FROM webhook")).scalar_one(),
        }


def _opened(eng: Engine) -> dict[str, object]:
    with Session(eng) as s:
        box = s.execute(select(TicketMailbox)).scalar_one()
        person = s.execute(select(Principal).where(Principal.sub.like("sealed-%"))).scalar_one()
        return {
            "imap": box.imap_password,
            "smtp": box.smtp_password,
            "paperless": s.execute(select(PaperlessSettings.token)).scalar_one(),
            "vapid": s.execute(select(PushVapidKey.private_pem)).scalar_one(),
            "calendar": person.calendar_token,
            "calendar_hash": person.calendar_token_hash,
            "webhook": s.execute(select(Webhook.secret)).scalar_one(),
        }


_PLAIN = {
    "imap": "imap-geheim",
    "smtp": "smtp-geheim",
    "paperless": "paperless-token",
    "vapid": "-----BEGIN PRIVATE KEY-----x",
    "calendar": _TOKEN,
    "calendar_hash": hashlib.sha256(_TOKEN.encode()).hexdigest(),
    "webhook": b"webhook-secret-bytes",
}


def test_each_secret_rests_sealed(eng: Engine) -> None:
    with Session(eng) as s:
        area = TicketArea(name="Sealed")
        s.add(area)
        s.flush()
        s.add_all(
            [
                TicketMailbox(
                    area_id=area.id,
                    address="box@example.org",
                    imap_host="mail.example.org",
                    imap_port=993,
                    imap_user="box",
                    imap_password="imap-geheim",
                    smtp_host="mail.example.org",
                    smtp_port=465,
                    smtp_user="box",
                    smtp_password="smtp-geheim",
                    done_folder="Erledigt",
                ),
                PaperlessSettings(id=1, base_url="https://p.example.org", token="paperless-token"),
                PushVapidKey(id=1, private_pem="-----BEGIN PRIVATE KEY-----x", public_key="pub"),
                Principal(sub=f"sealed-{uuid.uuid4()}", calendar_token=_TOKEN),
                Webhook(name="w", url="https://h.example.org", secret=b"webhook-secret-bytes"),
            ]
        )
        s.commit()

    raw = _raw(eng)
    assert all(is_sealed(value) for value in raw.values())
    assert not any("geheim" in v or "token" in v or "secret" in v for v in raw.values())
    assert _opened(eng) == _PLAIN


def test_the_migration_seals_plain_rows(eng: Engine, alembic_cfg: Config) -> None:
    command.downgrade(alembic_cfg, _BEFORE)
    try:
        with eng.begin() as conn:
            area = conn.execute(
                text(
                    "INSERT INTO ticket_area (id, name) "
                    "VALUES (gen_random_uuid(), 'Alt') RETURNING id"
                )
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO ticket_mailbox (id, area_id, address, imap_host, imap_port, "
                    "imap_user, imap_password, smtp_host, smtp_port, smtp_user, smtp_password, "
                    "done_folder) VALUES (gen_random_uuid(), :a, 'box@example.org', "
                    "'mail.example.org', 993, 'box', 'imap-geheim', 'mail.example.org', 465, "
                    "'box', 'smtp-geheim', 'Erledigt')"
                ),
                {"a": area},
            )
            conn.execute(
                text(
                    "INSERT INTO paperless_settings (id, base_url, token) "
                    "VALUES (1, 'https://p.example.org', 'paperless-token')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO push_vapid_key (id, private_pem, public_key) "
                    "VALUES (1, '-----BEGIN PRIVATE KEY-----x', 'pub')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO principal (id, sub, calendar_token) "
                    "VALUES (gen_random_uuid(), 'sealed-old', :t)"
                ),
                {"t": _TOKEN},
            )
            conn.execute(
                text(
                    "INSERT INTO webhook (id, name, url, secret) VALUES "
                    "(gen_random_uuid(), 'w', 'https://h.example.org', :s)"
                ),
                {"s": b"webhook-secret-bytes"},
            )
    finally:
        command.upgrade(alembic_cfg, "head")

    assert all(is_sealed(value) for value in _raw(eng).values())
    assert _opened(eng) == _PLAIN
