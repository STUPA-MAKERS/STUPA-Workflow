"""Mail-Template-Katalog (#12): Vollständigkeit + Drift-Freiheit.

Sichert zu, dass (a) jeder Katalog-Eintrag DE+EN für Betreff/Text hat, (b) der
Katalog die *gleichen* Builtin-Objekte referenziert wie die Versender (kein
Auseinanderlaufen von Editor-Anzeige und tatsächlichem Versand) und (c) jeder
real versendete ``template_key`` im Katalog steht.
"""

from __future__ import annotations

from app.modules.notifications import action_dispatcher, auto, comments
from app.modules.notifications import service as svc
from app.modules.notifications.templates_catalogue import (
    CATALOGUE_BY_KEY,
    TEMPLATE_CATALOGUE,
)


def test_every_spec_has_de_and_en() -> None:
    for spec in TEMPLATE_CATALOGUE:
        for lang in ("de", "en"):
            assert spec.subject_i18n.get(lang), f"{spec.key} subject {lang}"
            assert spec.body_i18n.get(lang), f"{spec.key} body {lang}"


def test_keys_unique() -> None:
    keys = [s.key for s in TEMPLATE_CATALOGUE]
    assert len(keys) == len(set(keys))


def test_builtins_are_shared_objects() -> None:
    # Drift-Frei: Katalog referenziert dieselben dicts wie die Versender.
    assert CATALOGUE_BY_KEY["status_update"].subject_i18n is svc._BUILTIN_NOTIFY_SUBJECT  # noqa: SLF001
    assert CATALOGUE_BY_KEY["magic_link"].body_i18n is svc._BUILTIN_MAGIC_LINK_BODY  # noqa: SLF001
    assert CATALOGUE_BY_KEY["task_new"].subject_i18n is action_dispatcher._BUILTIN_TASK_SUBJECT  # noqa: SLF001
    assert CATALOGUE_BY_KEY["comment_team"].body_i18n is comments._BUILTIN_TEAM_BODY  # noqa: SLF001
    assert CATALOGUE_BY_KEY["meeting_created"].subject_i18n is auto._BUILTIN_MEETING_SUBJECT  # noqa: SLF001
    assert CATALOGUE_BY_KEY["role_revoked"].body_i18n is auto._BUILTIN_ROLE_REVOKED_BODY  # noqa: SLF001


def test_worker_reminder_uses_catalogue() -> None:
    import worker.task_reminders as tr

    assert tr._BUILTIN_REMINDER_SUBJECT is CATALOGUE_BY_KEY["task_reminder"].subject_i18n  # noqa: SLF001


def test_all_sent_keys_are_catalogued() -> None:
    # Jeder real versendete template_key (siehe Versender) muss editierbar sein.
    sent = {
        "status_update",
        "task_new",
        "task_reminder",
        "deadline_approaching",
        "comment_applicant",
        "comment_team",
        "meeting_created",
        "role_assigned",
        "role_revoked",
        "delegation_granted",
        "delegation_revoked",
        "magic_link",
    }
    assert sent <= set(CATALOGUE_BY_KEY)
