"""seed: rollen+rechte, gremien, gremium-rollen, mail-templates, site-config, budgets

Revision ID: 0002_seed
Revises: 0001_baseline
Create Date: 2026-06-10 00:00:02

Pre-Alpha-Squash (#initialdata): **alle** Seed-Daten an einem Ort, in finaler Form
(die frühere Grant-dann-Rework-Historie ist eingedampft). Reihenfolge =
Abhängigkeitsreihenfolge. Feste/deterministische IDs → downgrade-bar.

1. **Globale Rollen** (admin/member/manager/protocol/finance) + ``role_permission``
   im finalen 17-Permission-Katalog (``app.shared.permissions``). ``admin`` hält
   den vollen Katalog.
2. **Mail-Templates** ``magic_link``, ``status_update``, ``deadline_approaching``.
3. **Site-Config** v1 (aktiv, leeres Branding) — ``GET /api/site-config`` liefert
   immer eine aktive Version.
4. **Standard-Gremien** ``StuPa`` + ``AStA``.
5. **Pflicht-Gremium-Rollen** je Gremium (``vorstand``/``manager``/``member``),
   Permissions synchron mit ``FORCED_GREMIUM_ROLES`` (admin/gremium_roles.py).
6. **Standard-Budgets** ``VSM`` (VS-Mittel, voller Haushaltsplan-Baum) + ``QSM``
   (QS-Mittel, ohne Unterknoten).

**Keine** Standard-Antragstypen und **keine** Standard-Formulare (#initialdata).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_seed"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --------------------------------------------------------------- table handles
_role = sa.table(
    "role",
    sa.column("id", sa.Uuid),
    sa.column("key", sa.Text),
    sa.column("name_i18n", JSONB),
)
_role_permission = sa.table(
    "role_permission",
    sa.column("role_id", sa.Uuid),
    sa.column("permission", sa.Text),
)
_gremium = sa.table(
    "gremium",
    sa.column("id", sa.Uuid),
    sa.column("name", sa.Text),
    sa.column("slug", sa.Text),
    sa.column("cd_variant", sa.Text),
    sa.column("default_lang", sa.Text),
)
_gremium_role = sa.table(
    "gremium_role",
    sa.column("id", sa.Uuid),
    sa.column("gremium_id", sa.Uuid),
    sa.column("key", sa.Text),
    sa.column("name_i18n", JSONB),
    sa.column("permissions", JSONB),
)
_mail_template = sa.table(
    "mail_template",
    sa.column("id", sa.Uuid),
    sa.column("key", sa.Text),
    sa.column("subject_i18n", JSONB),
    sa.column("body_i18n", JSONB),
    sa.column("body_html_i18n", JSONB),
    sa.column("placeholders", JSONB),
)
_site_config = sa.table(
    "site_config_version",
    sa.column("id", sa.Uuid),
    sa.column("version", sa.Integer),
    sa.column("active", sa.Boolean),
    sa.column("branding", JSONB),
)
_budget = sa.table(
    "budget",
    sa.column("id", sa.Uuid),
    sa.column("parent_id", sa.Uuid),
    sa.column("gremium_id", sa.Uuid),
    sa.column("key", sa.Text),
    sa.column("path_key", sa.Text),
    sa.column("name", sa.Text),
    sa.column("color", sa.Text),
    sa.column("accepted_state_keys", JSONB),
    sa.column("denied_state_keys", JSONB),
)

# ------------------------------------------------------------------ 1. roles
ROLE_IDS = {
    "admin": "00000000-0000-0000-0000-0000000000a1",
    "member": "00000000-0000-0000-0000-0000000000a2",
    "manager": "00000000-0000-0000-0000-0000000000a3",
    "protocol": "00000000-0000-0000-0000-0000000000a4",
    "finance": "00000000-0000-0000-0000-0000000000a5",
}
ROLE_NAMES = {
    "admin": {"de": "Administrator", "en": "Administrator"},
    "member": {"de": "Mitglied", "en": "Member"},
    "manager": {"de": "Sachbearbeitung", "en": "Manager"},
    "protocol": {"de": "Protokoll", "en": "Protocol"},
    "finance": {"de": "Finanzen", "en": "Finance"},
}
# Finaler Permission-Katalog (17 Keys, app.shared.permissions). admin = alles.
_FULL = (
    "application.read",
    "application.create",
    "application.transition",
    "application.manage",
    "form.configure",
    "flow.configure",
    "vote.cast",
    "vote.manage",
    "meeting.manage",
    "budget.view",
    "budget.manage",
    "budget.export",
    "application.export",
    "webhook.manage",
    "audit.read",
    "admin.config",
    "admin.roles",
)
ROLE_PERMISSIONS = {
    "admin": list(_FULL),
    "member": ["application.read", "vote.cast"],
    "manager": [
        "application.read",
        "application.create",
        "application.transition",
        "vote.manage",
        "meeting.manage",
        "budget.view",
        "budget.manage",
        "budget.export",
        "application.export",
    ],
    "protocol": ["application.read", "meeting.manage"],
    "finance": [
        "application.read",
        "budget.view",
        "budget.manage",
        "budget.export",
    ],
}

# --------------------------------------------------------- 4./5. gremien + roles
_STUPA_ID = "00000000-0000-0000-0000-0000000060e1"
_ASTA_ID = "00000000-0000-0000-0000-0000000060e3"
_GREMIEN = [
    (_STUPA_ID, "StuPa", "stupa", "stupa"),
    (_ASTA_ID, "AStA", "asta", "asta"),
]
# Pflicht-Gremium-Rollen (synchron mit FORCED_GREMIUM_ROLES, admin/gremium_roles.py).
_ALL_G = ["session.manage", "vote.manage", "vote.cast", "protocol.write"]
_FORCED_GREMIUM_ROLES = [
    ("vorstand", {"de": "Vorstand", "en": "Board"}, list(_ALL_G)),
    ("manager", {"de": "Manager", "en": "Manager"}, list(_ALL_G)),
    ("member", {"de": "Mitglied", "en": "Member"}, ["vote.cast"]),
]

# ------------------------------------------------------------- 2. mail templates
_MAIL_TEMPLATES = [
    {
        "id": "00000000-0000-0000-0000-0000000000e1",
        "key": "magic_link",
        "subject_i18n": {
            "de": "Ihr Zugangslink zur Antragsplattform",
            "en": "Your access link for the application platform",
        },
        "body_i18n": {
            "de": (
                "Hallo,\n\nüber diesen Link gelangen Sie zu Ihrem Antrag:\n{{ link }}\n\n"
                "Der Link ist zeitlich begrenzt gültig. Wenn Sie das nicht angefordert "
                "haben, ignorieren Sie diese Mail.\n"
            ),
            "en": (
                "Hello,\n\nuse this link to access your application:\n{{ link }}\n\n"
                "The link is valid for a limited time. If you did not request it, "
                "ignore this email.\n"
            ),
        },
        "body_html_i18n": {},
        "placeholders": {"link": "Magic-Link-URL"},
    },
    {
        "id": "00000000-0000-0000-0000-0000000000e2",
        "key": "status_update",
        "subject_i18n": {
            "de": "Statusänderung Ihres Antrags",
            "en": "Your application status changed",
        },
        "body_i18n": {
            "de": "Hallo,\n\nder Status Ihres Antrags hat sich geändert: {{ status }}.\n",
            "en": "Hello,\n\nyour application status has changed: {{ status }}.\n",
        },
        "body_html_i18n": {},
        "placeholders": {"status": "Neuer Status (Label)"},
    },
    {
        "id": "00000000-0000-0000-0000-0000000000e3",
        "key": "deadline_approaching",
        "subject_i18n": {
            "de": "Erinnerung: Frist läuft bald ab",
            "en": "Reminder: deadline approaching",
        },
        "body_i18n": {
            "de": (
                "Hallo,\n\neine Frist zu Ihrem Antrag läuft bald ab "
                "(fällig am {{ dueAt }}).\n\nBitte handeln Sie rechtzeitig.\n"
            ),
            "en": (
                "Hello,\n\na deadline for your application is approaching "
                "(due on {{ dueAt }}).\n\nPlease act in time.\n"
            ),
        },
        "body_html_i18n": {},
        "placeholders": {
            "deadlineId": "Frist-ID",
            "dueAt": "Fälligkeitszeitpunkt (ISO-8601)",
        },
    },
]
_SITE_CONFIG_ID = "00000000-0000-0000-0000-0000000000c1"

# --------------------------------------------------------------- 6. budget tree
_NS = uuid.UUID("00000000-0000-0000-0000-00000000b0d6")


def _node_id(path_key: str) -> str:
    return str(uuid.uuid5(_NS, path_key))


# (key, name, children). Haushaltsplan: Einnahmen 1–5, Ausgaben 6–11. Doppelte
# Nummern unter demselben Eltern +1 (Hilfskräfte 123→124); gestrichene Ressorts
# (134 Internationalität, 136 Demokratie/Politische Bildung) ausgelassen.
_VSM_TREE: list = [
    ("1", "Beiträge", []),
    ("2", "Einnahmen aus wirtschaftlicher Betätigung", [
        ("100", "Wirtschaftliche Betätigung", []),
        ("200", "BgA Campusfest", []),
    ]),
    ("3", "Einnahmen aus nicht wirtschaftlicher Betätigung", []),
    ("4", "Entnahmen aus Rücklagen", []),
    ("5", "Sonstige Einnahmen", []),
    ("6", "Personalausgaben", [
        ("60", "Personalausgaben", [
            ("120", "Haushaltsbeauftragte", []),
            ("123", "Sekretariat", []),
            ("124", "Hilfskräfte", []),
        ]),
        ("61", "Aufwandsentschädigung", []),
    ]),
    ("7", "Sächliche Verwaltungsausgaben", []),
    ("8", "Zuschüsse", [
        ("80", "an zentrale Einrichtungen (Ressorts)", [
            ("120", "Ressort Finanzen", []),
            ("121", "Ressort Marketing & Kommunikation", []),
            ("122", "Ressort Studierendenwerk", []),
            ("123", "Ressort Verwaltung", []),
            ("124", "Ressort Wahlen", []),
            ("130", "Ressort Campusattraktivität", []),
            ("131", "Ressort IT & Digitalisierung", []),
            ("132", "Ressort STUPA MAKERS", []),
            ("133", "Ressort Hochschulsport", []),
            ("135", "Ressort Kultur & Events", []),
            ("137", "Ressort Nachhaltigkeit", []),
            ("138", "Ressort Diversity & Awareness", []),
            ("139", "Netzwerke und Kooperation", []),
        ]),
        ("81", "an dezentrale Einrichtungen", [
            ("810", "Zuschüsse an Fachschaften", [
                ("310", "Life Science (LS)", []),
                ("320", "ESB Business School (ESB)", []),
                ("360", "Nachhaltigkeit und Technologie (NXT)", []),
                ("330", "Informatik (INF)", []),
                ("340", "Technik (TEC)", []),
                ("350", "Texoversum (TEX)", []),
            ]),
            ("811", "Zuschüsse an studentische Initiativen und Vereine", [
                ("400", "SIV-Projekte", []),
            ]),
        ]),
    ]),
    ("9", "Zuwendungen an Stellen außerh. der Studierendenschaft", []),
    ("10", "Ausgaben aus wirtschaftlicher Betätigung", [
        ("100", "BgA STUPA", []),
        ("200", "BgA Campusfest", []),
    ]),
    ("11", "Zuführung Rücklagen", []),
]


def _flatten(nodes: list, parent_path: str, parent_id: str | None, out: list) -> None:
    for key, name, children in nodes:
        path_key = f"{parent_path}-{key}"
        node_id = _node_id(path_key)
        out.append(
            {
                "id": node_id,
                "parent_id": parent_id,
                "gremium_id": None,  # nur Top-Level trägt gremium_id
                "key": key,
                "path_key": path_key,
                "name": name,
                "color": None,
                "accepted_state_keys": [],
                "denied_state_keys": [],
            }
        )
        _flatten(children, path_key, node_id, out)


def upgrade() -> None:
    # 1. Rollen + Rechte.
    op.bulk_insert(
        _role,
        [
            {"id": ROLE_IDS[key], "key": key, "name_i18n": ROLE_NAMES[key]}
            for key in ROLE_IDS
        ],
    )
    op.bulk_insert(
        _role_permission,
        [
            {"role_id": ROLE_IDS[key], "permission": perm}
            for key, perms in ROLE_PERMISSIONS.items()
            for perm in perms
        ],
    )

    # 2. Mail-Templates.
    op.bulk_insert(_mail_template, _MAIL_TEMPLATES)

    # 3. Site-Config v1 (aktiv, leeres Branding).
    op.bulk_insert(
        _site_config,
        [{"id": _SITE_CONFIG_ID, "version": 1, "active": True, "branding": {}}],
    )

    # 4. Standard-Gremien.
    op.bulk_insert(
        _gremium,
        [
            {
                "id": gid,
                "name": name,
                "slug": slug,
                "cd_variant": variant,
                "default_lang": "de",
            }
            for gid, name, slug, variant in _GREMIEN
        ],
    )

    # 5. Pflicht-Gremium-Rollen je Gremium (deterministische IDs via uuid5).
    op.bulk_insert(
        _gremium_role,
        [
            {
                "id": str(uuid.uuid5(_NS, f"grole:{gid}:{rkey}")),
                "gremium_id": gid,
                "key": rkey,
                "name_i18n": rname,
                "permissions": rperms,
            }
            for gid, *_ in _GREMIEN
            for rkey, rname, rperms in _FORCED_GREMIUM_ROLES
        ],
    )

    # 6. Standard-Budgets: VSM (voller Baum) + QSM (leer). Top-Level an StuPa.
    rows: list = [
        {
            "id": _node_id("VSM"),
            "parent_id": None,
            "gremium_id": _STUPA_ID,
            "key": "VSM",
            "path_key": "VSM",
            "name": "VS-Mittel",
            "color": None,
            "accepted_state_keys": [],
            "denied_state_keys": [],
        },
        {
            "id": _node_id("QSM"),
            "parent_id": None,
            "gremium_id": _STUPA_ID,
            "key": "QSM",
            "path_key": "QSM",
            "name": "QS-Mittel",
            "color": None,
            "accepted_state_keys": [],
            "denied_state_keys": [],
        },
    ]
    _flatten(_VSM_TREE, "VSM", _node_id("VSM"), rows)
    op.bulk_insert(_budget, rows)


def downgrade() -> None:
    conn = op.get_bind()
    # Budgets zuerst, tiefste Ebene voran (Self-FK RESTRICT) — Top-Budgets tragen
    # gremium_id, daher VOR dem Gremium-Delete (sonst CASCADE-vs-RESTRICT-Konflikt).
    # Tiefster Knoten VSM-8-81-810-330 = 4 Striche.
    for depth in range(4, -1, -1):
        conn.execute(
            sa.text(
                "DELETE FROM budget WHERE "
                "(path_key = 'VSM' OR path_key LIKE 'VSM-%' "
                " OR path_key = 'QSM' OR path_key LIKE 'QSM-%') "
                "AND length(path_key) - length(replace(path_key, '-', '')) = :d"
            ).bindparams(d=depth)
        )
    # Gremien (CASCADE → gremium_role), dann Rechte/Rollen/Templates/Site-Config.
    conn.execute(
        sa.text(
            "DELETE FROM gremium WHERE id IN (CAST(:s AS uuid), CAST(:a AS uuid))"
        ).bindparams(s=_STUPA_ID, a=_ASTA_ID)
    )
    role_ids = list(ROLE_IDS.values())
    op.execute(
        sa.delete(_role_permission).where(_role_permission.c.role_id.in_(role_ids))
    )
    op.execute(sa.delete(_role).where(_role.c.id.in_(role_ids)))
    _mail_ids = [t["id"] for t in _MAIL_TEMPLATES]
    op.execute(sa.delete(_mail_template).where(_mail_template.c.id.in_(_mail_ids)))
    op.execute(sa.delete(_site_config).where(_site_config.c.id == _SITE_CONFIG_ID))
