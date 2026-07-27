"""Seed: roles, permissions, Gremien, gremium roles, mail templates, site config, budgets.

Revision ID: 0002_seed
Revises: 0001_baseline
Create Date: 2026-06-10 00:00:02

Pre-alpha squash (#initialdata): all seed data sits here in its final form. The
grant-then-rework history of before is gone. The step order is the dependency order.
Fixed and deterministic IDs keep the downgrade possible.

1. Global roles (admin/member/manager/protocol/finance) plus `role_permission` for the
   final 17-permission catalog (`app.shared.permissions`). `admin` holds the full
   catalog.
2. Mail templates `magic_link`, `status_update` and `deadline_approaching`.
3. Site config v1 (active, empty branding). `GET /api/site-config` must always return
   an active version.
4. Default Gremien `StuPa` and `AStA`.
5. Forced gremium roles for each Gremium (`vorstand`/`manager`/`member`). The
   permissions stay in sync with `FORCED_GREMIUM_ROLES` (admin/gremium_roles.py).
6. Default budgets `VSM` (VS-Mittel, full budget-plan tree) and `QSM` (QS-Mittel,
   without child nodes).

This revision seeds no default application types and no default forms (#initialdata).
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
# The final permission catalog. Keep it in sync with app.shared.permissions.
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
    "account.manage",
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
        "account.manage",
        "application.export",
    ],
    "protocol": ["application.read", "meeting.manage"],
    "finance": [
        "application.read",
        "budget.view",
        "budget.manage",
        "budget.export",
        "account.manage",
    ],
}

_STUPA_ID = "00000000-0000-0000-0000-0000000060e1"
_ASTA_ID = "00000000-0000-0000-0000-0000000060e3"
_GREMIEN = [
    (_STUPA_ID, "StuPa", "stupa", "stupa"),
    (_ASTA_ID, "AStA", "asta", "asta"),
]
# Forced gremium roles. Keep them in sync with FORCED_GREMIUM_ROLES
# (admin/gremium_roles.py).
_ALL_G = ["session.manage", "vote.manage", "vote.cast", "protocol.write"]
_FORCED_GREMIUM_ROLES = [
    ("vorstand", {"de": "Vorstand", "en": "Board"}, list(_ALL_G)),
    ("manager", {"de": "Manager", "en": "Manager"}, list(_ALL_G)),
    ("member", {"de": "Mitglied", "en": "Member"}, ["vote.cast"]),
]

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

_NS = uuid.UUID("00000000-0000-0000-0000-00000000b0d6")


def _node_id(path_key: str) -> str:
    return str(uuid.uuid5(_NS, path_key))


# (key, name, children). Budget plan: income 1–5, expenses 6–11. A key that repeats
# under the same parent gets +1 (Hilfskräfte 123→124). The dropped Ressorts stay out
# (134 Internationalität, 136 Demokratie/Politische Bildung).
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
                "gremium_id": None,  # only a top-level node carries a gremium_id
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

    op.bulk_insert(_mail_template, _MAIL_TEMPLATES)

    op.bulk_insert(
        _site_config,
        [{"id": _SITE_CONFIG_ID, "version": 1, "active": True, "branding": {}}],
    )

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
    # Delete the budgets first, deepest level first, because the self FK is RESTRICT.
    # The top budgets carry a gremium_id, so they must go BEFORE the Gremium delete.
    # Otherwise CASCADE and RESTRICT conflict. The deepest node VSM-8-81-810-330 has
    # 4 dashes.
    for depth in range(4, -1, -1):
        conn.execute(
            sa.text(
                "DELETE FROM budget WHERE "
                "(path_key = 'VSM' OR path_key LIKE 'VSM-%' "
                " OR path_key = 'QSM' OR path_key LIKE 'QSM-%') "
                "AND length(path_key) - length(replace(path_key, '-', '')) = :d"
            ).bindparams(d=depth)
        )
    # The Gremium delete cascades to gremium_role, so that table needs no own delete.
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
