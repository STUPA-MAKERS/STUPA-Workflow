"""API schemas for the applications module.

These models shape the requests and the responses for application CRUD, the
timeline, the version history, the list and the comments. The API emits the PII
in ``ApplicationOut.applicant`` only to an authorized principal or to the
applicant.

``ApplicationOut`` names ``CaptureOut``, which this module defines later, so the module
rebuilds the model at the end.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.modules.applications.diff import DataDiff
from app.modules.files.schemas import MessageAttachmentOut, MessageFilesIn
from app.shared.altcha import AltchaSolutionStr
from app.shared.i18n import DEFAULT_LANG, I18nMap, Lang
from app.shared.mentions import MAX_MENTIONS
from app.shared.people import PersonRef


class _CamelModel(BaseModel):
    """Base model with camelCase aliases in JSON.

    The fields also populate by their Python name.
    """

    model_config = ConfigDict(populate_by_name=True)


class ApplicationCreate(_CamelModel):
    """Create an application.

    The server validates ``data`` against the effective form. An anonymous
    submission must carry ``altcha`` and ``applicantEmail``. The server verifies
    the ALTCHA solution. A logged-in user needs no ALTCHA. The server derives an
    empty ``applicantEmail`` or ``applicantName`` from the account. The router
    enforces the fields that an anonymous submission requires.

    ``attachmentIds`` and ``draftToken`` bind the draft uploads of the wizard.
    With them, every reference in a ``file`` field must be one of
    ``attachmentIds``.

    Attributes:
        applicant_email: Optional in the schema, because the account supplies it for a
            logged-in user. For an anonymous submission the router enforces it and
            answers 422.
        applicant_name: Display name, capped against DoS.
        altcha: The schema validates the structure and answers 422 for a malformed
            value. ``require_altcha`` runs the cryptographic verification.
        attachment_ids: Draft uploads of the wizard. The create binds these drafts of
            the token in its own transaction. A list without a token answers 422. Both
            stay optional, because the upload after the create
            (``POST /applications/{id}/attachments``) still works.
    """

    type_id: UUID = Field(alias="typeId")
    data: dict[str, Any]
    applicant_email: EmailStr | None = Field(default=None, alias="applicantEmail")
    applicant_name: str | None = Field(default=None, alias="applicantName", max_length=256)
    lang: Lang = DEFAULT_LANG
    altcha: AltchaSolutionStr | None = None
    attachment_ids: list[UUID] = Field(
        default_factory=list, alias="attachmentIds", max_length=100
    )
    draft_token: str | None = Field(
        default=None, alias="draftToken", min_length=1, max_length=128
    )


class OnBehalfCreate(_CamelModel):
    """Capture an application on behalf of an applicant.

    The applicant is EITHER an existing account (``applicantPrincipalId``) OR a guest
    with ``applicantName`` and ``applicantEmail``. The schema rejects a mix and a
    missing applicant with 422. ``data`` goes through the same validation as a normal
    submission. ``receivedOn`` defaults to the day of the capture in the local
    timezone; a date in the future answers 422. ``intake`` is the free-text intake
    channel ("Eingang"), for example "per PDF".

    ``attachmentIds`` and ``draftToken`` bind draft uploads, as on
    ``POST /applications``.
    """

    type_id: UUID = Field(alias="typeId")
    data: dict[str, Any]
    applicant_principal_id: UUID | None = Field(default=None, alias="applicantPrincipalId")
    applicant_email: EmailStr | None = Field(default=None, alias="applicantEmail")
    applicant_name: str | None = Field(
        default=None, alias="applicantName", min_length=1, max_length=256
    )
    received_on: date | None = Field(default=None, alias="receivedOn")
    intake: str | None = Field(default=None, max_length=500)
    lang: Lang = DEFAULT_LANG
    attachment_ids: list[UUID] = Field(
        default_factory=list, alias="attachmentIds", max_length=100
    )
    draft_token: str | None = Field(
        default=None, alias="draftToken", min_length=1, max_length=128
    )

    @model_validator(mode="after")
    def _one_applicant(self) -> OnBehalfCreate:
        guest = self.applicant_email is not None or self.applicant_name is not None
        if self.applicant_principal_id is not None and guest:
            raise ValueError(
                "Give either applicantPrincipalId or applicantName and applicantEmail."
            )
        if self.applicant_principal_id is None and (
            self.applicant_email is None or not (self.applicant_name or "").strip()
        ):
            raise ValueError(
                "A guest applicant needs applicantName and applicantEmail."
            )
        return self


class ApplicantCandidateOut(_CamelModel):
    """One account that the capture dialog offers as the applicant."""

    id: UUID
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None


class ApplicationCreated(_CamelModel):
    """201 response of ``POST /applications``, with the new id only."""

    application_id: UUID = Field(alias="applicationId")


class StateOut(_CamelModel):
    """A flow state as the application shows it.

    Attributes:
        kind: State kind. The frontend shows approve and reject actions for
            ``approval``.
    """

    id: UUID
    key: str
    label: I18nMap
    color: str | None = None
    edit_allowed: bool = Field(alias="editAllowed")
    kind: str = "normal"


class ApplicantOut(_CamelModel):
    """Applicant PII, visible to an authorized identity only."""

    email: str | None = None
    name: str | None = None
    anonymized: bool = False


class ApplicationOut(_CamelModel):
    """One application with its current state and the view flags of the requester.

    Attributes:
        vote_gremium_id: The Gremium that decides the current vote state (snapshot),
            else null.
        can_edit: The requester may edit or delete: a manager, a holder of
            ``application.edit_any`` or the creator.
        can_edit_locked: The requester holds ``application.edit_any``, so a state with
            ``editAllowed`` false does not lock the edit for this requester.
        is_owner: The requester is the creator, that is the applicant. This gates the
            anonymization request (GDPR Art. 17), because only the data subject may
            ask, never the administration.
        archived_at: When it was archived, or null. The client shows the badge from
            it. Archiving is NOT anonymization: the record is complete and readable,
            it has only left the working list.
        state_since: Time of the last status change: the newest status event, else the
            creation time. The status page shows "since" from it.
        hidden_keys: The ``isPII`` field keys that the server removed from ``data`` for
            this reader. Empty for a reader with the PII right. The edit form leaves
            out these fields, because a patch keeps their stored values, and a missing
            key in ``data`` alone does not tell "removed" from "never answered".
        capture: Set when a person captured the application on behalf of the
            applicant.
        approved_amount: The approved amount of the valid decision, null = as
            requested.
        decision: The valid decision (approval with deviations), null before any
            decision.
    """

    id: UUID
    type_id: UUID = Field(alias="typeId")
    state: StateOut | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    vote_gremium_id: UUID | None = Field(default=None, alias="voteGremiumId")
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    amount: Decimal | None = None
    currency: str | None = None
    data: dict[str, Any]
    version: int
    lang: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    applicant: ApplicantOut | None = None
    can_edit: bool = Field(default=False, alias="canEdit")
    can_edit_locked: bool = Field(default=False, alias="canEditLocked")
    is_owner: bool = Field(default=False, alias="isOwner")
    archived_at: datetime | None = Field(default=None, alias="archivedAt")
    state_since: datetime | None = Field(default=None, alias="stateSince")
    hidden_keys: list[str] = Field(default_factory=list, alias="hiddenKeys")
    capture: CaptureOut | None = None
    approved_amount: Decimal | None = Field(default=None, alias="approvedAmount")
    decision: DecisionOut | None = None


class DecisionOut(_CamelModel):
    """The valid decision on an application (approval with deviations).

    ``approvedAmount`` null means "as requested". The applicant view gets the same
    block without ``voteId``. No view carries vote counts.
    """

    requested_amount: Decimal | None = Field(default=None, alias="requestedAmount")
    approved_amount: Decimal | None = Field(default=None, alias="approvedAmount")
    amount_deviates: bool = Field(default=False, alias="amountDeviates")
    conditions: list[str] = Field(default_factory=list)
    decided_at: datetime = Field(alias="decidedAt")
    vote_id: UUID | None = Field(default=None, alias="voteId")
    gremium_name: str | None = Field(default=None, alias="gremiumName")
    meeting_title: str | None = Field(default=None, alias="meetingTitle")
    agenda_position: int | None = Field(default=None, alias="agendaPosition")


class TimelineDecisionOut(_CamelModel):
    """The decision that a status event carried, for the history line."""

    requested_amount: Decimal | None = Field(default=None, alias="requestedAmount")
    approved_amount: Decimal | None = Field(default=None, alias="approvedAmount")
    amount_deviates: bool = Field(default=False, alias="amountDeviates")
    condition_count: int = Field(default=0, alias="conditionCount")


class ApplicationPatch(_CamelModel):
    """Update the application data.

    A new version follows only when ``state.editAllowed`` is true.
    """

    data: dict[str, Any]


ActorKind = Literal["principal", "applicant", "system", "gremium", "deleted"]


class ActorOut(_CamelModel):
    """The resolved actor of a timeline event, a version or a comment.

    The frontend renders this object and never a raw stored value. ``kind`` tells
    the type of the actor:

    - ``principal``: a member. ``displayName`` holds the name, or the email when
      the account has no name. ``principalId`` is the id of the account, for the
      avatar (``GET /principals/{id}/avatar``).
    - ``applicant``: the applicant through the magic link. No name, because the
      name is PII.
    - ``system``: an automatic action. ``key`` names the source, for example
      ``deadlines`` for ``system:deadlines``. A plain ``system`` gives the key
      ``auto``.
    - ``gremium``: the applicant view shows the Gremium for each action of a
      member. ``displayName`` holds the Gremium name, or null when the
      application has no Gremium.
    - ``deleted``: the stored ``sub`` names no known account, or the account was
      anonymized. No name and no id.

    Attributes:
        principal_id: Only for ``principal``. The applicant view never holds a member
            id, because it shows the Gremium instead of the member.
    """

    kind: ActorKind
    key: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    principal_id: UUID | None = Field(default=None, alias="principalId")

    def legacy(self, raw: str) -> str | None:
        """Return the old string value of the ``actor`` field for this actor.

        A principal and a Gremium give the name. The applicant and the system give
        the stored key, for example ``applicant`` or ``system:deadlines``. A
        deleted account gives null, so that no raw ``sub`` leaves the server.
        """
        if self.kind in ("principal", "gremium"):
            return self.display_name
        if self.kind in ("applicant", "system"):
            return raw
        return None


class CaptureOut(_CamelModel):
    """How an application captured on behalf of the applicant came in.

    ``capturedBy`` follows the actor rules of the timeline: the applicant view shows
    the Gremium instead of the member.
    """

    captured_by: ActorOut | None = Field(default=None, alias="capturedBy")
    captured_at: datetime = Field(alias="capturedAt")
    received_on: date | None = Field(default=None, alias="receivedOn")
    intake: str | None = None


class TimelineEventOut(_CamelModel):
    """One status change of the timeline.

    In the applicant view (magic link or creator), ``actor`` names the Gremium of the
    application for every action that the applicant did not do.

    Attributes:
        transition_label: The i18n label of the fired transition. Null for the creation
            event and for a revert, which fire no transition.
        actor: The display string of the actor: a name, ``applicant`` or a
            ``system:*`` key. Never a raw ``sub``. The frontend renders ``actorInfo``.
        vote_id: The vote whose close fired this event. Null for every other event,
            for a deleted vote, and in the applicant view (no vote access).
        vote_deleted: A vote close fired this event (note ``vote:<result>``) and a
            meeting delete deleted the vote with its meeting. The application keeps
            the status that the vote decided.
        decision: The decision that this status change carried (approved amount,
            number of conditions), else null.
    """

    from_state_id: UUID | None = Field(default=None, alias="fromStateId")
    to_state_id: UUID = Field(alias="toStateId")
    to_state: StateOut | None = Field(default=None, alias="toState")
    transition_label: I18nMap | None = Field(default=None, alias="transitionLabel")
    actor: str | None = None
    actor_info: ActorOut | None = Field(default=None, alias="actorInfo")
    at: datetime
    note: str | None = None
    vote_id: UUID | None = Field(default=None, alias="voteId")
    vote_deleted: bool = Field(default=False, alias="voteDeleted")
    decision: TimelineDecisionOut | None = None


class VersionOut(_CamelModel):
    """One submission version.

    ``changedKeys`` holds the keys of the added, removed and changed fields. The
    applicant view gets the metadata only: ``data`` and ``diff`` are null.
    A reader without the PII right gets ``data``, ``diff`` and ``changedKeys``
    without the ``isPII`` fields.

    Attributes:
        changed_by: Same rules as ``TimelineEventOut.actor``. The frontend renders
            ``changedByInfo``.
    """

    version: int
    data: dict[str, Any] | None = None
    diff: DataDiff | None = None
    changed_keys: list[str] = Field(default_factory=list, alias="changedKeys")
    changed_by: str | None = Field(default=None, alias="changedBy")
    changed_by_info: ActorOut | None = Field(default=None, alias="changedByInfo")
    at: datetime


class ApplicationListItem(_CamelModel):
    """One row of the application list.

    Attributes:
        title: Title for the list column, from the system title field
            ``data['title']``.
        approved_amount: The approved amount of the valid decision, null = as
            requested.
    """

    id: UUID
    type_id: UUID = Field(alias="typeId")
    title: str | None = None
    state: StateOut | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    amount: Decimal | None = None
    approved_amount: Decimal | None = Field(default=None, alias="approvedAmount")
    currency: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    #: Set when the row is archived, so a combined list can mark it.
    archived_at: datetime | None = Field(default=None, alias="archivedAt")
    #: Time of the last status change, for "waiting since".
    state_since: datetime | None = Field(default=None, alias="stateSince")


class ShareCreate(_CamelModel):
    """Ask for a public link. Both fields are optional.

    Attributes:
        ttl_days: The service bounds it to 1..365 days, default 30. "Never" is not on
            offer, because an expiry makes a forgotten link stop working by itself.
        label: A private note of the creator, for example "an die Fachschaft
            geschickt". Never shown publicly.
    """

    ttl_days: int | None = Field(default=None, alias="ttlDays", ge=1, le=365)
    label: str | None = Field(default=None, max_length=200)


class ShareOut(_CamelModel):
    """One share link as its creator sees it.

    ``url`` carries the plaintext token and is therefore present ONLY in the response that
    created the link. Listing existing links returns it as null, because the server cannot
    reconstruct a token it only ever stored a hash of — and would not hand it back if it
    could.
    """

    id: UUID
    created_at: datetime = Field(alias="createdAt")
    expires_at: datetime = Field(alias="expiresAt")
    revoked_at: datetime | None = Field(default=None, alias="revokedAt")
    created_by: str | None = Field(default=None, alias="createdBy")
    label: str | None = None
    url: str | None = None


class CommentCreate(MessageFilesIn, _CamelModel):
    """A new comment. ``attachmentIds`` and ``draftToken`` bind its files.

    The body may be empty only with at least one file.

    Attributes:
        body: Capped against DoS, so one comment cannot grow without a bound in the
            database and in the mail render. A longer body answers 422.
        mentions: The principal ids of the mentioned members (at most 50, duplicates
            drop). Each one must be in ``GET /applications/{id}/mentionable``, else 422
            ``mention_not_member``. A caller who does not read the internal comments
            (the applicant view) may not mention anybody.
    """

    body: str = Field(max_length=10_000)
    visibility: Literal["internal", "public"] = "public"
    mentions: list[UUID] = Field(default_factory=list, max_length=MAX_MENTIONS)


class CommentPatch(_CamelModel):
    """Replace the body of a comment in place.

    The visibility is not patchable. A public comment is already out, so
    switching it to internal hides it only from the applicant who read it. The
    delete is the path for that case.

    ``mentions`` null keeps the stored mentions; a list replaces them, with the same
    rules as the create. Only a mention that the list adds gets a mail.
    """

    body: str = Field(min_length=1, max_length=10_000)
    mentions: list[UUID] | None = Field(default=None, max_length=MAX_MENTIONS)


class CommentOut(_CamelModel):
    """One comment as the viewer sees it.

    Attributes:
        is_own: The requesting viewer wrote the comment. The frontend aligns the chat
            bubble by this flag.
        attachments: The files of the comment, oldest first. They are fixed at the
            send.
        mentions: The mentioned members, in the stored order. The applicant view gets
            an empty list, because the applicant never sees a member name. An erased
            account shows as the deleted person (``principalId`` and ``displayName``
            null).
    """

    id: UUID
    author: str | None = None
    author_kind: Literal["principal", "applicant"] = Field(alias="authorKind")
    author_info: ActorOut | None = Field(default=None, alias="authorInfo")
    body: str
    visibility: Literal["internal", "public"]
    at: datetime
    is_own: bool = Field(default=False, alias="isOwn")
    attachments: list[MessageAttachmentOut] = Field(default_factory=list)
    mentions: list[PersonRef] = Field(default_factory=list)


ApplicationOut.model_rebuild()
