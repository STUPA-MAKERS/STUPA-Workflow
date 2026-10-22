"""Deep links from a mail to the element that it refers to.

Every mail carries one absolute link to its element: the application, the task, the
meeting, the protocol, the ticket, the to-do, the poll or the admin page. The service puts the
URL into the template context as ``link``. When the rendered text does not contain the
URL, the service adds one labelled line to the text and one button to the HTML
layout. A DB override that does not use ``{{ link }}`` therefore still gets the link.

The link of an application depends on the reader:

- A team member and an applicant with an account open ``/applications/{id}``. The
  login is the usual one.
- A guest applicant (``Application.created_by`` is None) opens ``/antrag/{id}``. The
  page loads the application with the applicant cookie of the last magic link. Without
  the cookie it asks the reader to open the link of the confirmation mail again. The
  mail never mints a new magic-link token, because a token in every status mail would
  multiply the access tokens of the application.

A comment mail to a reader of ``/applications/{id}`` ends its link with
``#comment-{comment id}``. The page then opens the comments and scrolls to that
comment. The link of a guest has no fragment. A mention mail of a ticket note ends
its link with ``#note-{note id}`` in the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.settings import Settings

#: The element that a link opens. It selects the label of the line and the button.
LinkTarget = Literal[
    "application", "task", "meeting", "protocol", "privacy", "ticket", "todo", "poll"
]

_LABELS: dict[str, dict[str, str]] = {
    "application": {"de": "Antrag öffnen", "en": "Open the application"},
    "task": {"de": "Aufgabe öffnen", "en": "Open the task"},
    "meeting": {"de": "Sitzung öffnen", "en": "Open the meeting"},
    "protocol": {"de": "Protokoll öffnen", "en": "Open the protocol"},
    "privacy": {"de": "Löschanträge öffnen", "en": "Open the erasure requests"},
    "ticket": {"de": "Ticket öffnen", "en": "Open the ticket"},
    "todo": {"de": "To-Do öffnen", "en": "Open the to-do"},
    "poll": {"de": "Umfrage öffnen", "en": "Open the poll"},
}


@dataclass(frozen=True, slots=True)
class MailLink:
    """An absolute URL and the kind of element that it opens."""

    url: str
    target: LinkTarget

    def label(self, lang: str) -> str:
        """Return the label of the link in ``lang`` (fallback: German)."""
        table = _LABELS[self.target]
        return table.get(lang, table["de"])


def _base(settings: Settings) -> str:
    return settings.public_base_url.rstrip("/")


def application_link(
    settings: Settings,
    application_id: UUID | str,
    *,
    guest: bool = False,
    comment_id: UUID | str | None = None,
) -> MailLink:
    """Return the link to an application.

    ``guest`` selects the public applicant page for an applicant without an account.
    ``comment_id`` adds the fragment ``#comment-{id}`` to the link of
    ``/applications/{id}``, which opens the comments at that comment. The link of a
    guest stays without a fragment.
    """
    if guest:
        return MailLink(f"{_base(settings)}/antrag/{application_id}", "application")
    url = f"{_base(settings)}/applications/{application_id}"
    if comment_id is not None:
        url += f"#comment-{comment_id}"
    return MailLink(url, "application")


def task_link(settings: Settings, application_id: UUID | str) -> MailLink:
    """Return the link to the task of an application (team only)."""
    return MailLink(f"{_base(settings)}/tasks/{application_id}", "task")


def meeting_link(settings: Settings, meeting_id: UUID | str) -> MailLink:
    """Return the link to a meeting."""
    return MailLink(f"{_base(settings)}/meetings/{meeting_id}", "meeting")


def protocol_link(settings: Settings, meeting_id: UUID | str) -> MailLink:
    """Return the link to the protocol, which the meeting page holds."""
    return MailLink(f"{_base(settings)}/meetings/{meeting_id}", "protocol")


def public_protocol_url(settings: Settings, protocol_id: UUID | str) -> str:
    """Return the URL of the public version of a protocol."""
    return f"{_base(settings)}/protokolle/{protocol_id}"


def privacy_admin_link(settings: Settings) -> MailLink:
    """Return the link to the erasure requests of the privacy admin page."""
    return MailLink(f"{_base(settings)}/admin/privacy", "privacy")


def ticket_link(
    settings: Settings, ticket_id: UUID | str, *, note_id: UUID | str | None = None
) -> MailLink:
    """Return the link to a ticket: the team and the reporter account open the same path.

    ``note_id`` adds the fragment ``#note-{id}``, which opens the ticket at that note.
    """
    url = f"{_base(settings)}/tickets/{ticket_id}"
    if note_id is not None:
        url += f"#note-{note_id}"
    return MailLink(url, "ticket")


def todo_link(settings: Settings, card_id: UUID | str) -> MailLink:
    """Return the link to a card: the card id only.

    The page opens the board the card is on at the click, so a mail stays valid when the
    card moves to another board.
    """
    return MailLink(f"{_base(settings)}/todos?card={card_id}", "todo")


def vote_link(settings: Settings, vote_id: UUID | str) -> MailLink:
    """Return the link to a poll on the page "Abstimmungen" (``/voting/{id}``)."""
    return MailLink(f"{_base(settings)}/voting/{vote_id}", "poll")
