"""API-Schemata des Live-Vote/Meeting-Moduls (T-16, api.md §4)."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MeetingStatus = Literal["planned", "live", "closed"]


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class MeetingCreate(_CamelModel):
    """``POST /api/meetings`` — Sitzung anlegen (Status ``planned``)."""

    gremium_id: UUID = Field(alias="gremiumId")
    title: str = Field(min_length=1)
    # Termin ist Pflicht: ohne Datum/Uhrzeit lässt sich keine Sitzung planen.
    date: _date
    start_time: _time = Field(alias="startTime")
    # Optionale End-Uhrzeit (#ics); fehlt sie, nimmt der iCal-Feed 1 h Dauer an.
    end_time: _time | None = Field(default=None, alias="endTime")
    # Genau ein zugewiesener Protokollant (Mitglied des Gremiums).
    protokollant_id: UUID | None = Field(default=None, alias="protokollantId")

    @model_validator(mode="after")
    def _end_after_start(self) -> MeetingCreate:
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("endTime must be after startTime")
        return self


class MeetingPatch(_CamelModel):
    """``PATCH /api/meetings/{id}`` — Sitzungs-Steuerung/Planung.

    Mindestens ein Feld muss gesetzt sein; jede Änderung publiziert ``meeting_state``.
    """

    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    status: MeetingStatus | None = None
    date: _date | None = None
    start_time: _time | None = Field(default=None, alias="startTime")
    end_time: _time | None = Field(default=None, alias="endTime")
    protokollant_id: UUID | None = Field(default=None, alias="protokollantId")

    @model_validator(mode="after")
    def _at_least_one(self) -> MeetingPatch:
        # ``date``/``protokollantId`` zählen mit: geplante Sitzungen vorab terminieren
        # bzw. den Protokollanten (um)setzen.
        managed = {
            "date",
            "start_time",
            "end_time",
            "protokollant_id",
        } & self.model_fields_set
        if self.status is None and self.active_application_id is None and not managed:
            raise ValueError(
                "at least one of 'status', 'activeApplicationId', 'date', "
                "'startTime', 'endTime' or 'protokollantId' required"
            )
        return self


class MeetingVoteOut(_CamelModel):
    """Eine an die Sitzung gebundene Abstimmung (für die Sitzungssteuerung)."""

    id: UUID
    # NULL = generische Beschlussfrage (Freitext-TOP), kein Antrag.
    application_id: UUID | None = Field(default=None, alias="applicationId")
    # An welchen TOP die Abstimmung gebunden ist (für die Gruppierung im FE).
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    question: str | None = None
    # Optionen (für die Stimmabgabe im FE).
    options: list[str] = Field(default_factory=list)
    # ``cancelled``: Antrag hat den vote-State manuell verlassen (Wahl abgebrochen).
    status: Literal["draft", "open", "closed", "cancelled"]
    result: str | None = None
    # Aktueller Stimmenstand (Option → Anzahl) + führende Option — bleibt nach einem
    # Reload erhalten (vorher nur über den Live-WS-Pfad sichtbar).
    counts: dict[str, int] | None = None
    leading: str | None = None
    # Teilnahme-Fortschritt (abgestimmte vs. anwesende Mitglieder) + ``revealed``: ob
    # ``counts``/``leading`` sichtbar sind (geschlossen oder alle Anwesenden haben
    # abgestimmt und nicht geheim), sonst verdeckt (#vote-progress).
    voted: int = 0
    present: int = 0
    revealed: bool = True
    # Grund einer Ablehnung (nach Close): ``quorum`` = Quorum verfehlt, ``majority`` =
    # Mehrheit verfehlt. ``None`` solange offen oder bei ``passed``/``tie``.
    failed_reason: Literal["quorum", "majority"] | None = Field(
        default=None, alias="failedReason"
    )


class MeetingOut(_CamelModel):
    """Sitzungs-State (``GET /api/meetings/{id}``)."""

    id: UUID
    gremium_id: UUID = Field(alias="gremiumId")
    gremium_name: str | None = Field(default=None, alias="gremiumName")
    title: str
    date: _date | None = None
    start_time: _time | None = Field(default=None, alias="startTime")
    end_time: _time | None = Field(default=None, alias="endTime")
    # Automatisch beim Schließen gesetzt (#14) — »Ende« der Protokoll-Titelseite.
    closed_at: _datetime | None = Field(default=None, alias="closedAt")
    status: MeetingStatus
    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    protocol_id: UUID | None = Field(default=None, alias="protocolId")
    created_at: _datetime = Field(alias="createdAt")
    protokollant_id: UUID | None = Field(default=None, alias="protokollantId")
    protokollant_name: str | None = Field(default=None, alias="protokollantName")
    # Ist der ANFRAGENDE Principal der zugewiesene Protokollant dieser Sitzung? Das FE
    # kann das nicht selbst berechnen (es kennt nur `sub`, nicht die interne
    # principal_id), deshalb serverseitig auflösen (#protokollant-view).
    is_protokollant: bool = Field(default=False, alias="isProtokollant")
    # Master-Flag fürs FE: darf der Principal die Sitzung **führen** (Protokoll/TOPs/
    # Status)? = Protokollant oder Sitzungsverwalter. Granulare Flags darunter.
    can_control: bool = Field(default=False, alias="canControl")
    can_manage: bool = Field(default=False, alias="canManage")
    can_write: bool = Field(default=False, alias="canWrite")
    can_manage_votes: bool = Field(default=False, alias="canManageVotes")
    can_vote: bool = Field(default=False, alias="canVote")
    # An die Sitzung gebundene Abstimmungen (Sitzungssteuerung).
    votes: list[MeetingVoteOut] = Field(default_factory=list)


TimelineDirection = Literal["past", "upcoming"]


class MeetingPage(_CamelModel):
    """Cursor-Seite der Sitzungs-Timeline (#104).

    Keyset-paginiert um *jetzt* herum: ``upcoming`` läuft chronologisch vorwärts
    (frühestes zuerst), ``past`` rückwärts (jüngstes zuerst). ``nextCursor`` ist
    ``None``, sobald in dieser Richtung keine weiteren Sitzungen folgen.
    """

    items: list[MeetingOut]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


AttendanceStatus = Literal["present", "excused", "absent"]


class AttendanceOut(_CamelModel):
    """Anwesenheit eines Gremium-Mitglieds für eine Sitzung (#Meetings)."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    # ``None`` = noch nicht erfasst (Mitglied der Roster ohne Eintrag).
    status: AttendanceStatus | None = None
    source: Literal["self", "lead"] | None = None
    # Ist der anfragende Principal dieses Mitglied (für die Selbst-Markierung)?
    is_self: bool = Field(default=False, alias="isSelf")


class MeetingMemberOut(_CamelModel):
    """Aktuelles Gremium-Mitglied — Protokollant-Kandidat beim Anlegen einer Sitzung."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None


class AttendanceSetBody(_CamelModel):
    """``PUT …/attendance/{principalId}`` bzw. ``…/me`` — Anwesenheit setzen."""

    status: AttendanceStatus


class AgendaItemOut(_CamelModel):
    """Tagesordnungspunkt: ein zugeordneter Antrag **oder** Freitext-TOP (#10/#58)."""

    id: UUID
    application_id: UUID | None = Field(default=None, alias="applicationId")
    title: str | None = None
    # Markdown-Text dieses TOP (pro-TOP-Editor).
    body: str | None = None
    position: int = 0
    # Nicht-öffentlich: im öffentlichen Protokoll-PDF redigiert (#PII-Re-Add).
    non_public: bool = Field(default=False, alias="nonPublic")
    # Aktueller Status des Antrags (i18n-Label), z. B. zum Anzeigen in der Liste.
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")


class AssignableApplicationOut(_CamelModel):
    """Antrag in einem Abstimmungs-State des Sitzungs-Gremiums (noch nicht auf der TO)."""

    application_id: UUID = Field(alias="applicationId")
    title: str | None = None
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")


class MeetingVoteOpenBody(_CamelModel):
    """``POST /meetings/{id}/votes`` — Beschlussfrage eines TOP öffnen (Live-Vote).

    Bindet eine neue Abstimmung an den TOP (``agendaItemId``) und öffnet sie sofort.
    Bei Antrags-TOPs ist genau **eine** Abstimmung erlaubt (sie feuert beim Schließen
    den pass/fail-Branch des Antrags); Freitext-TOPs erlauben **mehrere** generische
    Beschlussfragen. ``question`` (Beschlussfrage) wandert ins Protokoll-Snippet.
    """

    agenda_item_id: UUID = Field(alias="agendaItemId")
    question: str | None = None
    options: list[str] = Field(default_factory=lambda: ["yes", "no", "abstain"])
    majority_rule: Literal["simple", "absolute", "two_thirds"] = Field(
        default="simple", alias="majorityRule"
    )
    secret: bool = False
    eligible_count: int | None = Field(default=None, alias="eligibleCount", ge=0)
    # Explizites Prozent-Quorum (0–100). ``None`` ⇒ Default des Gremiums (falls gesetzt).
    quorum_percent: int | None = Field(
        default=None, alias="quorumPercent", ge=0, le=100
    )

    @model_validator(mode="after")
    def _min_options(self) -> MeetingVoteOpenBody:
        if len(self.options) < 2:
            raise ValueError("at least two options are required")
        return self


class AgendaAddBody(_CamelModel):
    """``POST /meetings/{id}/agenda`` — TOP setzen: Antrag **oder** Freitext.

    Genau eins von ``applicationId`` / ``title`` ist Pflicht.
    """

    application_id: UUID | None = Field(default=None, alias="applicationId")
    title: str | None = Field(default=None, min_length=1)
    non_public: bool = Field(default=False, alias="nonPublic")

    @model_validator(mode="after")
    def _one_of(self) -> AgendaAddBody:
        if (self.application_id is None) == (self.title is None):
            raise ValueError("exactly one of applicationId or title is required")
        return self


class AgendaBodyBody(_CamelModel):
    """``PATCH …/agenda/{itemId}`` — Markdown-Text und/oder Titel eines TOP setzen.

    ``title`` benennt nur **Freitext-TOPs** um (Antrag-TOPs erben den Titel vom
    Antrag); ``body`` setzt den Markdown-Text. Beide sind optional.
    """

    body: str | None = None
    title: str | None = Field(default=None, min_length=1)
    non_public: bool | None = Field(default=None, alias="nonPublic")


class AgendaReorderBody(_CamelModel):
    """``PUT …/agenda/order`` — TOPs in der gelieferten Reihenfolge anordnen."""

    item_ids: list[UUID] = Field(alias="itemIds")
