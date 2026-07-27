"""Mail template catalogue (#12): completeness and no drift.

The tests check three properties. Every catalogue entry carries DE and EN for the
subject and the body. The catalogue references the same builtin objects as the senders,
so the editor view and the real mail cannot drift apart. Every `template_key` that the
code really sends is part of the catalogue.
"""

from __future__ import annotations

from app.modules.notifications import action_dispatcher, auto, comments
from app.modules.notifications import service as svc
from app.modules.notifications.templates_catalogue import (
    CATALOGUE_BY_KEY,
    STATUS_UPDATE_TEAM_BODY,
    STATUS_UPDATE_TEAM_SUBJECT,
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
    assert CATALOGUE_BY_KEY["status_update"].subject_i18n is svc._BUILTIN_NOTIFY_SUBJECT  # noqa: SLF001
    assert CATALOGUE_BY_KEY["magic_link"].body_i18n is svc._BUILTIN_MAGIC_LINK_BODY  # noqa: SLF001
    assert CATALOGUE_BY_KEY["task_new"].subject_i18n is action_dispatcher._BUILTIN_TASK_SUBJECT  # noqa: SLF001
    assert CATALOGUE_BY_KEY["comment_team"].body_i18n is comments._BUILTIN_TEAM_BODY  # noqa: SLF001
    assert CATALOGUE_BY_KEY["meeting_created"].subject_i18n is auto._BUILTIN_MEETING_SUBJECT  # noqa: SLF001
    assert CATALOGUE_BY_KEY["role_revoked"].body_i18n is auto._BUILTIN_ROLE_REVOKED_BODY  # noqa: SLF001


def test_status_update_team_mirrors_status_update() -> None:
    # Team-facing default of the notify action (bug #2). It uses the same kind and the
    # same placeholder set as `status_update`, backed by the single-source builtins.
    team = CATALOGUE_BY_KEY["status_update_team"]
    base = CATALOGUE_BY_KEY["status_update"]
    assert team.kind == "status_update"
    assert set(team.placeholders) == set(base.placeholders)
    assert team.subject_i18n is STATUS_UPDATE_TEAM_SUBJECT
    assert team.body_i18n is STATUS_UPDATE_TEAM_BODY
    assert team.key == svc.TEAM_NOTIFY_TEMPLATE_KEY


def test_worker_reminder_uses_catalogue() -> None:
    import worker.task_reminders as tr

    assert tr._BUILTIN_REMINDER_SUBJECT is CATALOGUE_BY_KEY["task_reminder"].subject_i18n  # noqa: SLF001


def test_all_sent_keys_are_catalogued() -> None:
    # Every template_key that a sender really uses must stay editable in the catalogue.
    sent = {
        "status_update",
        "status_update_team",
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
