"""The fixed catalog of the webhook events and their payload fields.

A webhook subscribes only to an event of `EVENTS` (§F/integrations/webhooks/002411). For
each event it chooses fields from the `fields` of that event (§F/integrations/webhooks/002412).
A field with `personal=True` is personal data: the dialog marks it, and a new subscription
starts with it off (§F/integrations/webhooks/002413). The ID keys are always in the body.

The table of the protocol spec P/integrations/webhooks/000963 mirrors this module. The
example values feed the payload preview of the dialog (§F/integrations/webhooks/002415)
and the test delivery (§F/integrations/webhooks/002416).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

#: The event names of the catalog, in the order of the dialog.
WebhookEventName = Literal[
    "application.created",
    "application.updated",
    "application.transition",
    "application.archived",
    "comment.created",
    "vote.opened",
    "vote.closed",
    "meeting.created",
    "meeting.started",
    "meeting.closed",
    "protocol.finalized",
    "booking.created",
    "invoice.created",
    "ticket.created",
]

#: The event of a test delivery. It is not in the catalog, because no webhook
#: subscribes to it.
TEST_EVENT = "webhook.test"

EventGroup = Literal["applications", "votes", "meetings", "protocols", "budget", "tickets"]

_ID = "3f6c1d2e-8a4b-4c5d-9e6f-7a8b9c0d1e2f"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field that a webhook can choose for an event."""

    key: str
    example: Any
    personal: bool = False


@dataclass(frozen=True, slots=True)
class EventSpec:
    """One event of the catalog: its group, its ID keys and its fields."""

    name: WebhookEventName
    group: EventGroup
    id_keys: tuple[str, ...]
    fields: tuple[FieldSpec, ...]

    @property
    def field_keys(self) -> frozenset[str]:
        """Return the keys of the fields of the event."""
        return frozenset(f.key for f in self.fields)


def _ref(name: str) -> dict[str, str]:
    return {"id": _ID, "name": name}


_APPLICATION_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("title", "Zuschuss Sommerfest"),
    FieldSpec("type", _ref("Finanzantrag")),
    FieldSpec("gremium", _ref("StuPa")),
    FieldSpec("status", _ref("Eingereicht")),
    FieldSpec("amount", "125.00"),
    FieldSpec("currency", "EUR"),
    FieldSpec("approvedAmount", None),
    FieldSpec("url", "https://example.org/applications/" + _ID),
    FieldSpec("applicantName", "Erika Mustermann", personal=True),
    FieldSpec("applicantEmail", "erika@example.org", personal=True),
    FieldSpec("answers", {"title": "Zuschuss Sommerfest"}, personal=True),
)

_VOTE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("question", "Zuschuss Sommerfest bewilligen?"),
    FieldSpec("kind", "vote"),
    FieldSpec("gremium", _ref("StuPa")),
    FieldSpec("meetingId", _ID),
    FieldSpec("applicationId", _ID),
    FieldSpec("closesAt", "2026-11-23T20:00:00+00:00"),
    FieldSpec("url", "https://example.org/voting/" + _ID),
)

_MEETING_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("title", "3. ordentliche Sitzung"),
    FieldSpec("gremium", _ref("StuPa")),
    FieldSpec("date", "2026-11-23"),
    FieldSpec("startTime", "18:00:00"),
    FieldSpec("endTime", "20:00:00"),
    FieldSpec("location", "Raum 9-012"),
    FieldSpec("status", "planned"),
    FieldSpec("url", "https://example.org/meetings/" + _ID),
)

_CATALOG: tuple[EventSpec, ...] = (
    EventSpec("application.created", "applications", ("applicationId",), _APPLICATION_FIELDS),
    EventSpec("application.updated", "applications", ("applicationId",), _APPLICATION_FIELDS),
    EventSpec(
        "application.transition",
        "applications",
        ("applicationId", "transitionId", "statusEventId"),
        (
            *_APPLICATION_FIELDS,
            FieldSpec("fromStatus", _ref("Eingereicht")),
            FieldSpec("toStatus", _ref("Genehmigt")),
            FieldSpec("note", "Einstimmig", personal=True),
        ),
    ),
    EventSpec("application.archived", "applications", ("applicationId",), _APPLICATION_FIELDS),
    EventSpec(
        "comment.created",
        "applications",
        ("commentId", "applicationId"),
        (
            FieldSpec("visibility", "internal"),
            FieldSpec("applicationTitle", "Zuschuss Sommerfest"),
            FieldSpec("url", "https://example.org/applications/" + _ID),
            FieldSpec("body", "Bitte Angebot nachreichen.", personal=True),
            FieldSpec("authorName", "Max Mustermann", personal=True),
        ),
    ),
    EventSpec("vote.opened", "votes", ("voteId",), _VOTE_FIELDS),
    EventSpec(
        "vote.closed",
        "votes",
        ("voteId",),
        (
            *_VOTE_FIELDS,
            FieldSpec("result", "passed"),
            FieldSpec("counts", {"yes": 9, "no": 2, "abstain": 1}),
        ),
    ),
    EventSpec("meeting.created", "meetings", ("meetingId",), _MEETING_FIELDS),
    EventSpec("meeting.started", "meetings", ("meetingId",), _MEETING_FIELDS),
    EventSpec("meeting.closed", "meetings", ("meetingId",), _MEETING_FIELDS),
    EventSpec(
        "protocol.finalized",
        "protocols",
        ("protocolId", "meetingId"),
        (
            FieldSpec("meetingTitle", "3. ordentliche Sitzung"),
            FieldSpec("gremium", _ref("StuPa")),
            FieldSpec("finalizedAt", "2026-11-24T09:00:00+00:00"),
            FieldSpec("publicUrl", "https://example.org/public/protocols/" + _ID),
        ),
    ),
    EventSpec(
        "booking.created",
        "budget",
        ("bookingId",),
        (
            FieldSpec("kind", "expense"),
            FieldSpec("amount", "125.00"),
            FieldSpec("costCentre", _ref("Kultur")),
            FieldSpec("fiscalYear", _ref("2026")),
            FieldSpec("description", "Sommerfest Technik"),
            FieldSpec("applicationId", _ID),
            FieldSpec("url", "https://example.org/expenses?id=" + _ID),
        ),
    ),
    EventSpec(
        "invoice.created",
        "budget",
        ("invoiceId",),
        (
            FieldSpec("number", "RE-2026-0042"),
            FieldSpec("supplier", "Veranstaltungstechnik GmbH"),
            FieldSpec("grossAmount", "119.00"),
            FieldSpec("currency", "EUR"),
            FieldSpec("issueDate", "2026-11-20"),
            FieldSpec("dueDate", "2026-12-04"),
            FieldSpec("costCentre", _ref("Kultur")),
            FieldSpec("url", "https://example.org/invoices?id=" + _ID),
        ),
    ),
    EventSpec(
        "ticket.created",
        "tickets",
        ("ticketId",),
        (
            FieldSpec("number", "T-0042"),
            FieldSpec("kind", "problem"),
            FieldSpec("title", "Upload hängt"),
            FieldSpec("url", "https://example.org/tickets/" + _ID),
            FieldSpec("body", "Beim Hochladen passiert nichts.", personal=True),
            FieldSpec("reporterEmail", "erika@example.org", personal=True),
        ),
    ),
)

#: The catalog by event name.
EVENTS: Mapping[str, EventSpec] = {spec.name: spec for spec in _CATALOG}

assert tuple(EVENTS) == get_args(WebhookEventName), "catalog and WebhookEventName drift"


def example_payload(event: EventSpec, fields: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Return the example body of `event` with the chosen `fields` (preview and test)."""
    chosen = set(fields)
    body: dict[str, Any] = {"event": event.name, "occurredAt": "2026-11-23T09:00:00+00:00"}
    body.update(dict.fromkeys(event.id_keys, _ID))
    body["data"] = {f.key: f.example for f in event.fields if f.key in chosen}
    return body
