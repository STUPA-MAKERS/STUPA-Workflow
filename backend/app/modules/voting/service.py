"""Voting-Service (T-15, flows §4, api.md »voting«).

Lebenszyklus einer Abstimmung: ``create`` (draft) → ``open`` (Stimmberechtigte
zählen + Fenster setzen) → ``cast`` (Stimme, race-sicher über DB-Constraints) →
``close`` (auszählen → Ergebnis → ``flow.fire(result_branch)``).

**Race-Sicherheit.** Eine Stimme pro Berechtigtem wird auf DB-Ebene erzwungen:

* offen (``secret=false``): ``INSERT … ON CONFLICT (vote_id, voter_sub)`` —
  ``allowChange`` ⇒ ``DO UPDATE`` (Stimme aktualisieren, idempotent), sonst
  ``DO NOTHING`` und leeres ``RETURNING`` ⇒ 409 (Doppelstimme).
* geheim (``secret=true``): ``voted_marker`` (UNIQUE) trägt »hat abgestimmt«; die
  Stimme landet identitätslos in ``secret_ballot``. ``allowChange`` ist hier **ohne
  Wirkung** (anonyme Stimme nicht rückverknüpfbar) → zweite Abgabe ⇒ 409.

**RBAC fail-closed.** ``cast`` verlangt Mitgliedschaft in ``vote.eligible_group``
(zusätzlich zur ``vote.cast``-Permission im Router); fehlt sie ⇒ 403.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.delegations.service import voting_delegation_check
from app.modules.flow.dispatch import ActionDispatcher, NullActionDispatcher
from app.modules.flow.service import FlowService
from app.modules.voting import tally as tally_mod
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker
from app.modules.voting.schemas import (
    BallotAccepted,
    TallyOut,
    VoteClosed,
    VoteCreate,
    VoteOut,
)
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem


def open_tally_revealed(present: int, voted: int, expected: int) -> bool:
    """Reveal-Regel für offene, NICHT-geheime Votes (#vote-progress).

    Der laufende Stimmenstand wird erst sichtbar, wenn **alle erwarteten** Stimmen
    eingegangen sind — sonst leakt der Zwischenstand am Beamer/Voter. ``expected``
    ist der Nenner: anwesende Mitglieder **plus** aktive Stimm-Delegationen, deren
    Delegierende:r ABWESEND ist (für diese gibt der/die Empfänger:in eine
    Vertretungs-Stimme ab → ``voted`` zählt sie mit). Ohne diesen Aufschlag könnte
    ``voted`` ``present`` übersteigen, bevor alle Anwesenden gestimmt haben, und das
    Tally vorzeitig aufdecken. Geteilt mit dem Live-Vote-Reload-Pfad (livevote)."""
    return present > 0 and voted >= expected


class VotingService:
    """An eine ``AsyncSession`` (+ optionalen Flow-Dispatcher) gebundener Service."""

    def __init__(self, session: AsyncSession, dispatcher: ActionDispatcher | None = None) -> None:
        self.session = session
        self.dispatcher: ActionDispatcher = dispatcher or NullActionDispatcher()

    # ----------------------------------------------------------------- helpers
    async def _get_vote(self, vote_id: UUID, *, for_update: bool = False) -> Vote:
        """Vote laden; ``for_update`` sperrt die Zeile (cast/close-Serialisierung):
        ohne Lock kann eine Last-Sekunden-Stimme zwischen Auszählung und
        ``status=closed`` committen und fehlt dann im festgeschriebenen Ergebnis."""
        stmt = select(Vote).where(Vote.id == vote_id)
        if for_update:
            stmt = stmt.with_for_update()
        vote = (await self.session.execute(stmt)).scalar_one_or_none()
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        return vote

    async def delete(self, vote_id: UUID, *, meeting_id: UUID) -> None:
        """Eine an die Sitzung gebundene Abstimmung löschen (Ballots cascaden via FK).

        Nur Votes dieser Sitzung; der Aufrufer (Router) prüft die Berechtigung."""
        vote = await self._get_vote(vote_id)
        if vote.meeting_id != meeting_id:
            raise NotFoundError(f"vote {vote_id} not found in this meeting")
        await self.session.delete(vote)
        await self.session.flush()
        await self.session.commit()

    async def _get_application(self, application_id: UUID) -> Application:
        app = (
            await self.session.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    @staticmethod
    def _config(vote: Vote) -> VoteConfig:
        return VoteConfig.model_validate(vote.config)

    async def _aggregate(self, vote: Vote, config: VoteConfig) -> dict[str, int]:
        """Stimmen je Option zählen — offen aus ``ballot``, geheim aus ``secret_ballot``."""
        if config.secret:
            choices: Sequence[str | None] = (
                (
                    await self.session.execute(
                        select(SecretBallot.choice).where(SecretBallot.vote_id == vote.id)
                    )
                )
                .scalars()
                .all()
            )
        else:
            choices = (
                (await self.session.execute(select(Ballot.choice).where(Ballot.vote_id == vote.id)))
                .scalars()
                .all()
            )
        return tally_mod.tally(config.options, choices)

    async def _present_count(self, vote: Vote) -> int:
        """Anzahl **anwesender** Mitglieder der Sitzung (Reveal-Nenner). 0 ohne Sitzung."""
        if vote.meeting_id is None:
            return 0
        from app.modules.livevote.models import MeetingAttendance

        return (
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingAttendance)
                .where(
                    MeetingAttendance.meeting_id == vote.meeting_id,
                    MeetingAttendance.status == "present",
                )
            )
        ) or 0

    async def _absent_delegated_count(self, vote: Vote) -> int:
        """Aktive Stimm-Delegationen dieser Sitzung/dieses Gremiums, deren
        Delegierende:r NICHT anwesend ist (Reveal-Nenner-Aufschlag, #vote-progress).

        Für diese Delegationen gibt der/die Empfänger:in eine Vertretungs-Stimme ab,
        die ``voted`` mitzählt, obwohl der/die Delegierende nicht unter den Anwesenden
        ist. Ohne den Aufschlag könnte ``voted`` ``present`` früh übersteigen und das
        Tally vorzeitig aufdecken. ``eligible_group`` ist die Gremium-UUID als Text;
        passt sie nicht, gibt es keine Delegation (0)."""
        if vote.meeting_id is None:
            return 0
        try:
            gremium_id = UUID(vote.eligible_group)
        except (ValueError, TypeError):
            return 0
        from app.modules.delegations.models import MeetingDelegation
        from app.modules.livevote.models import MeetingAttendance

        present_subq = (
            select(MeetingAttendance.principal_id)
            .where(
                MeetingAttendance.meeting_id == vote.meeting_id,
                MeetingAttendance.status == "present",
            )
            .scalar_subquery()
        )
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingDelegation)
                .where(
                    MeetingDelegation.meeting_id == vote.meeting_id,
                    MeetingDelegation.gremium_id == gremium_id,
                    MeetingDelegation.delegate_voting.is_(True),
                    MeetingDelegation.delegator_principal_id.notin_(present_subq),
                )
            )
        ) or 0

    async def _tally_out(
        self, vote: Vote, config: VoteConfig, counts: dict[str, int], eligible: int
    ) -> TallyOut:
        """Tally + Teilnahme-Fortschritt. ``counts``/``leading`` sind nur sichtbar, wenn
        ``revealed``: geschlossen **oder** (nicht geheim **und** alle Anwesenden haben
        abgestimmt). Sitzungslose, offene, nicht-geheime Votes bleiben sofort sichtbar
        (kein »anwesend«-Begriff). Verdeckt ⇒ nur ``voted``/``present`` reisen mit."""
        voted = sum(counts.values())
        outcome = tally_mod.result(config, counts, eligible)
        # Anwesenden-Nenner nur abfragen, wenn er die Reveal-Entscheidung beeinflusst
        # (offener Vote mit Sitzung). Geschlossen/sitzungslos braucht keine Query.
        if vote.status == "closed":
            present, revealed = 0, True
        elif config.secret:
            present = await self._present_count(vote)
            revealed = False
        elif vote.meeting_id is None:
            present, revealed = 0, True
        else:
            present = await self._present_count(vote)
            # Erwartete Stimmen = Anwesende + Vertretungs-Stimmen abwesender
            # Delegierender (sonst leakt der Zwischenstand zu früh, #vote-progress).
            expected = present + await self._absent_delegated_count(vote)
            revealed = open_tally_revealed(present, voted, expected)
        return TallyOut(
            counts=counts if revealed else {},
            eligible=eligible,
            voted=voted,
            present=present,
            revealed=revealed,
            quorumMet=outcome.quorum_met,
            leading=outcome.leading if revealed else None,
            result=None,
        )

    def _to_out(self, vote: Vote, config: VoteConfig, tally_out: TallyOut) -> VoteOut:
        return VoteOut(
            id=vote.id,
            applicationId=vote.application_id,
            meetingId=vote.meeting_id,
            agendaItemId=getattr(vote, "agenda_item_id", None),
            question=getattr(vote, "question", None),
            eligibleGroup=vote.eligible_group,
            config=config,
            status=vote.status,  # type: ignore[arg-type]
            opensAt=vote.opens_at,
            closesAt=vote.closes_at,
            result=vote.result,  # type: ignore[arg-type]
            secret=config.secret,
            tally=tally_out,
        )

    # --------------------------------------------------------------- create
    async def create(
        self,
        application_id: UUID | None,
        payload: VoteCreate,
        *,
        meeting_id: UUID | None = None,
        agenda_item_id: UUID | None = None,
    ) -> VoteOut:
        """Abstimmung (``draft``) anlegen.

        ``application_id`` ist optional: ``None`` = generische Beschlussfrage eines
        Freitext-TOP (kein Antrag, kein Flow-Branch beim Close). ``meeting_id`` bindet
        die Abstimmung an eine Sitzung (Live-Vote, T-16); ``agenda_item_id`` an den TOP.
        """
        if application_id is not None:
            await self._get_application(application_id)
        vote = Vote(
            application_id=application_id,
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            eligible_group=payload.eligible_group,
            question=payload.question,
            config=payload.config.model_dump(by_alias=True),
            eligible_count=payload.eligible_count,
            opens_state_id=payload.opens_state_id,
            closes_at=payload.closes_at,
            result_branch_transition_id=payload.result_branch_transition_id,
            status="draft",
        )
        self.session.add(vote)
        await self.session.flush()
        await self.session.commit()
        config = payload.config
        empty = {opt: 0 for opt in config.options}
        return self._to_out(
            vote, config, await self._tally_out(vote, config, empty, vote.eligible_count or 0)
        )

    # ----------------------------------------------------------------- open
    async def open(self, vote_id: UUID, *, now: datetime) -> VoteOut:
        """``draft`` → ``open``: Zeitfenster öffnen.

        Der Quorum-Nenner (``eligible_count``) stammt aus dem maßgeblichen Roster und
        wird beim Anlegen gesetzt — **nicht** aus eingeloggten Usern abgeleitet (das
        wäre fail-open). Fehlt er, bleibt ein Prozent-Quorum fail-closed unerfüllt."""
        vote = await self._get_vote(vote_id)
        if vote.status != "draft":
            raise ConflictError(f"vote is {vote.status}, cannot open.", code="conflict")
        config = self._config(vote)
        vote.opens_at = now
        vote.status = "open"
        await self.session.flush()
        await self.session.commit()
        empty = {opt: 0 for opt in config.options}
        return self._to_out(
            vote, config, await self._tally_out(vote, config, empty, vote.eligible_count or 0)
        )

    # ----------------------------------------------------------------- cast
    async def cast(
        self,
        vote_id: UUID,
        principal: Principal,
        choice: str,
        *,
        now: datetime,
        as_delegation: bool = False,
    ) -> BallotAccepted:
        """Stimme abgeben. 409 (geschlossen/Doppel), 403 (nicht stimmberechtigt),
        422 (unbekannte Option).

        ``as_delegation=True`` gibt die VERTRETUNGS-Stimme ab (#delegation-rework):
        sie läuft unter dem ``sub`` des/der Delegierenden — eigene Stimme und
        Vertretungs-Stimme sind damit zwei getrennte Ballots (Transfer, kein
        Duplikat; der Unique-Constraint je (Vote, Voter) schützt beide einzeln)."""
        # Row-Lock serialisiert gegen close(): Status-Check und Ballot-Insert liegen
        # in derselben Transaktion — keine Stimme landet nach der Auszählung.
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError("vote is not open.", code="conflict")
        if vote.closes_at is not None and now >= vote.closes_at:
            raise ConflictError("voting window has closed.", code="conflict")
        # `blocked` = der Aufrufer hat sein Stimmrecht für DIESE Sitzung abgegeben.
        # `delegator_sub` = ihm wurde ein Stimmrecht übertragen (None = keins).
        blocked, delegator_sub = await voting_delegation_check(
            self.session, principal.sub, vote.meeting_id, vote.eligible_group, now
        )
        if as_delegation:
            if delegator_sub is None:
                raise ForbiddenError("No delegated voting right for this ballot.")
            voter_sub = delegator_sub
        else:
            if blocked:
                raise ForbiddenError("Voting right has been delegated to another member.")
            # Eigene Stimme: globales ``vote.cast`` + Gruppen-Mitgliedschaft (der
            # Router gated nur Auth, damit externe Stellvertreter durchkommen).
            if not principal.has("vote.cast") or not self._eligible_group_member(
                principal, vote.eligible_group
            ):
                raise ForbiddenError("Not eligible to vote in this ballot.")
            voter_sub = principal.sub
        config = self._config(vote)
        if choice not in config.options:
            raise ValidationProblem(
                "Unknown vote option.",
                errors=[{"field": "choice", "msg": "not in vote options"}],
            )
        if as_delegation:
            # Audit der Delegations-NUTZUNG; bei späterem 409 (Doppel) rollt die
            # Session-Dependency die Transaktion inkl. dieses Eintrags zurück.
            await audit_record(
                self.session,
                actor=principal.sub,
                action=AuditAction.DELEGATION_USE,
                target_type="vote",
                target_id=str(vote.id),
                data={"eligibleGroup": vote.eligible_group},
            )
        if config.secret:
            return await self._cast_secret(vote.id, voter_sub, choice)
        return await self._cast_open(vote.id, voter_sub, choice, config.allow_change)

    @staticmethod
    def _eligible_group_member(principal: Principal, eligible_group: str) -> bool:
        """Stimmberechtigung gegen ``eligible_group`` prüfen (AUD-066).

        Ist ``eligible_group`` eine Gremium-UUID (Sitzungs-/Antrags-Votes), MUSS der
        Cast über den namespaced ``vote:<uuid>``-Key laufen, den nur eine aktive
        ``vote.cast``-Mitgliedschaft setzt — ein deckungsgleicher OIDC-Gruppen-Claim
        kann die Gremium-Stimmberechtigung damit nicht fälschlich erfüllen. Für freie
        (Nicht-UUID-)Gruppen-Keys bleibt es bei der direkten OIDC-Gruppen-Prüfung.
        """
        try:
            UUID(eligible_group)
        except (ValueError, TypeError):
            return principal.in_group(eligible_group)
        return principal.in_group(vote_group_key(eligible_group))

    async def _cast_open(
        self, vote_id: UUID, voter_sub: str, choice: str, allow_change: bool
    ) -> BallotAccepted:
        values = {"vote_id": vote_id, "voter_sub": voter_sub, "choice": choice}
        if allow_change:
            # ``xmax = 0`` unterscheidet INSERT (Erst-Stimme → "cast") von dem durch
            # ON CONFLICT ausgelösten UPDATE (Änderung → "changed"): bei einem frisch
            # eingefügten Tupel ist die löschende Transaktions-ID 0.
            stmt = (
                pg_insert(Ballot)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_ballot_vote_voter",
                    set_={"choice": choice, "at": func.now()},
                )
                .returning(literal_column("(xmax = 0)").label("inserted"))
            )
            row = (await self.session.execute(stmt)).first()
            await self.session.commit()
            inserted = bool(row.inserted) if row is not None else False
            return BallotAccepted(status="cast" if inserted else "changed")

        stmt = (
            pg_insert(Ballot)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_ballot_vote_voter")
            .returning(Ballot.id)
        )
        inserted = (await self.session.execute(stmt)).first()
        if inserted is None:
            # ON CONFLICT DO NOTHING schrieb nichts → kein Rollback nötig; die
            # Session-Dependency (get_session) beendet die Transaktion bei der Exception.
            raise ConflictError("Already voted.", code="conflict")
        await self.session.commit()
        return BallotAccepted(status="cast")

    async def _cast_secret(self, vote_id: UUID, voter_sub: str, choice: str) -> BallotAccepted:
        # `voted_marker` (UNIQUE) trägt »hat abgestimmt« — der Identitäts-Anker. Nur
        # wenn er **neu** ist, wird die identitätslose Stimme geschrieben (keine
        # Verknüpfung choice↔voter; allowChange anonym nicht umsetzbar → 409).
        marker = (
            pg_insert(VotedMarker)
            .values(vote_id=vote_id, voter_sub=voter_sub)
            .on_conflict_do_nothing(constraint="uq_voted_marker_vote_voter")
            .returning(VotedMarker.id)
        )
        inserted = (await self.session.execute(marker)).first()
        if inserted is None:
            raise ConflictError("Already voted.", code="conflict")
        self.session.add(SecretBallot(vote_id=vote_id, choice=choice))
        await self.session.commit()
        return BallotAccepted(status="cast")

    # ------------------------------------------------------------------- get
    async def assert_can_read(self, vote: Vote, principal: Principal) -> None:
        """Lesezugriff auf einen Vote absichern (#sec-audit, Broken-Object-Level-Authz).

        Sitzungs-gebundene Votes folgen der Sitzungs-Sichtbarkeit (Mitglied/Teilnehmer/
        Delegations-Empfänger) wie ``MeetingService.assert_can_read``; sitzungslose
        (Antrags-/Entwurfs-)Votes verlangen eine globale Lese-/Verwaltungs-Permission.
        Ohne diese Prüfung konnte jede:r eingeloggte Nutzer:in per ``GET /api/votes/{id}``
        das Tally **fremder** Gremien lesen — inkl. geschlossener GEHEIM-Abstimmungen."""
        if "admin" in principal.roles:
            return
        if vote.meeting_id is not None:
            from app.modules.livevote.service import MeetingService

            await MeetingService(self.session).assert_can_read(vote.meeting_id, principal)
            return
        if (
            principal.has("vote.manage")
            or principal.has("application.read")
            or principal.has("application.read_all")
        ):
            return
        raise ForbiddenError("not allowed to view this vote")

    async def get_scoped(self, vote_id: UUID, principal: Principal) -> VoteOut:
        """Wie :meth:`get`, aber fail-closed gescopt auf den Lesekreis des Votes."""
        vote = await self._get_vote(vote_id)
        await self.assert_can_read(vote, principal)
        return await self.get(vote_id)

    # ---------------------------------------------------------- manage-scope
    async def _vote_gremium_id(
        self, *, meeting_id: UUID | None, eligible_group: str
    ) -> UUID | None:
        """Gremium eines Votes auflösen (#sec-audit, AUD-027).

        Sitzungs-gebundene Votes erben das Gremium der Sitzung; sitzungslose
        (Antrags-)Votes tragen das Gremium als ``eligible_group`` (Gremium-UUID-als-Text,
        s. ``MeetingRouter`` ``eligibleGroup=str(gremium_id)``). Ist ``eligible_group`` ein
        freier Gruppen-Key (keine UUID), gibt es kein auflösbares Gremium → ``None`` (dann
        bleibt nur die globale ``vote.manage`` / ``admin`` als Berechtigung)."""
        if meeting_id is not None:
            from app.modules.livevote.models import Meeting

            gid = await self.session.scalar(
                select(Meeting.gremium_id).where(Meeting.id == meeting_id)
            )
            if gid is not None:
                return gid
        try:
            return UUID(eligible_group)
        except (ValueError, TypeError):
            return None

    async def assert_can_manage_group(
        self, eligible_group: str, meeting_id: UUID | None, principal: Principal
    ) -> None:
        """Schreib-/Lifecycle-Zugriff (create/open/close/cancel) fail-closed gremium-scopen
        (#sec-audit, AUD-027), symmetrisch zu :meth:`assert_can_read`.

        Erlaubt für Admin, Halter der GLOBALEN ``vote.manage``-Permission **oder** eine
        Gremium-Rolle mit ``vote.manage`` für das Gremium des Votes (analog
        ``MeetingService.can_manage_votes``). Letzteres entsperrt legitime per-Gremium-
        Verwalter, die zuvor durch das global-only Router-Gate ausgeschlossen waren, und
        verhindert zugleich, dass ein org-weiter ``vote.manage``-Halter Abstimmungen
        FREMDER Gremien ohne Mitgliedschaft öffnet/schließt (Cross-Tenant-Mutation)."""
        if "admin" in principal.roles:
            return
        if principal.has("vote.manage"):
            return
        gremium_id = await self._vote_gremium_id(
            meeting_id=meeting_id, eligible_group=eligible_group
        )
        if gremium_id is not None:
            from app.modules.admin.gremium_roles import gremium_ids_with_permission

            if gremium_id in await gremium_ids_with_permission(
                self.session, principal.sub, "vote.manage"
            ):
                return
        raise ForbiddenError("not allowed to manage this vote")

    async def assert_can_manage(self, vote: Vote, principal: Principal) -> None:
        """Wie :meth:`assert_can_manage_group`, aber für einen bereits geladenen Vote."""
        await self.assert_can_manage_group(vote.eligible_group, vote.meeting_id, principal)

    async def assert_can_manage_vote(self, vote_id: UUID, principal: Principal) -> None:
        """Vote laden (404, falls fehlend) und :meth:`assert_can_manage` prüfen.

        Vom ``/votes/{id}/{open,close,cancel}``-Router VOR dem Lifecycle-Aufruf genutzt,
        damit open/close/cancel symmetrisch zu ``get_scoped`` fail-closed gremium-gescopt
        sind (#sec-audit, AUD-027). Der interne Live-Vote-/Cron-Pfad ruft die Lifecycle-
        Methoden direkt (eigenes Gate) und umgeht diese Prüfung bewusst."""
        vote = await self._get_vote(vote_id)
        await self.assert_can_manage(vote, principal)

    async def get(self, vote_id: UUID) -> VoteOut:
        """Vote-State + aggregiertes Tally (geheim: nur counts, nie Wähler).

        **Kein** Scope-Gate — interner Wiederverwendungs-Pfad (z. B. Tally-Broadcast
        nach ``cast``); der öffentliche Read-Endpunkt nutzt :meth:`get_scoped`."""
        vote = await self._get_vote(vote_id)
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        tally_out = await self._tally_out(vote, config, counts, vote.eligible_count or 0)
        if vote.status == "closed" and vote.result is not None:
            # Persistiert als Text-Spalte; Werte stammen aus tally.result() → Literal.
            stored_result = cast("tally_mod.VoteResult", vote.result)
            tally_out = tally_out.model_copy(
                update={
                    "result": stored_result,
                    "failed_reason": tally_mod.failed_reason(stored_result, tally_out.quorum_met),
                }
            )
        return self._to_out(vote, config, tally_out)

    # ---------------------------------------------------------------- cancel
    async def cancel(self, vote_id: UUID) -> VoteOut:
        """``open`` → ``cancelled`` (#12): Abbruch ohne Ergebnis und ohne Branch.

        Der Antrag bleibt im ``vote``-State — es kann ein neuer Vote angelegt oder
        ein manueller Ausgang gefeuert werden. Einzige der Ausweg, wenn das Quorum
        nicht zustande kommt (``close`` ist dann blockiert)."""
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError(f"vote is {vote.status}, cannot cancel.", code="conflict")
        vote.status = "cancelled"
        await self.session.commit()
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        return self._to_out(
            vote,
            config,
            await self._tally_out(vote, config, counts, vote.eligible_count or 0),
        )

    # ----------------------------------------------------------------- close
    async def close(
        self, vote_id: UUID, principal: Principal, *, now: datetime | None = None
    ) -> VoteClosed:
        """``open`` → ``closed``: auszählen → Ergebnis → ``flow.fire(result_branch)``.

        **Atomar**: Vote-Schließung (``status=closed`` + ``result``) und der
        ``voteResult``-Übergang werden in **einer** Transaktion committet (``fire``
        committet die vorgemerkten Vote-Änderungen mit). Schlägt ``fire`` fehl
        (Guard/Race), rollt die Session-Dependency alles zurück → der Vote bleibt
        **offen und wiederholbar** statt »zu, aber Branch nie gefeuert« (stuck).

        **Verfallene Quorum-Abstimmung (#stuck-vote).** Ein zeit-gebundener,
        quorum-gegateter Vote, dessen Fenster (``closes_at``) abgelaufen ist und
        dessen Quorum NICHT erreicht wurde, ist endgültig gescheitert: weitere
        Stimmen sind unmöglich (das Cast-Fenster ist zu). Beim manuellen Schließen
        (``now=None``) gilt das frühere fail-closed 409 (mehr Stimmen sammeln oder
        abbrechen). Übergibt der Aufrufer (Cron) jedoch ``now`` UND ist das Fenster
        bereits abgelaufen, wird der Vote als terminal QUORUM-VERFEHLT geschlossen
        und der ``fail``-Branch gefeuert — sonst hinge der Antrag ewig im ``vote``-
        State und der Cron würde denselben unschließbaren Vote im Sekundentakt
        erneut greifen."""
        # Row-Lock serialisiert gegen cast(): keine Last-Sekunden-Stimme zwischen
        # Auszählung und ``status=closed``.
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError(f"vote is {vote.status}, cannot close.", code="conflict")
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        eligible = vote.eligible_count or 0
        outcome = tally_mod.result(config, counts, eligible)

        # Fenster abgelaufen? Nur relevant, wenn der Aufrufer ``now`` mitgibt (Cron).
        window_expired = (
            now is not None and vote.closes_at is not None and now >= vote.closes_at
        )

        # Beschlussfähigkeit (#12): ohne erfülltes Quorum gibt es im Normalfall kein
        # gültiges Ergebnis — Schließen ist blockiert (409) statt still als »rejected«
        # zu enden. Ausweg: weitere Stimmen sammeln oder die Abstimmung abbrechen.
        # AUSNAHME (#stuck-vote): ist das Cast-Fenster bereits abgelaufen, sind keine
        # weiteren Stimmen mehr möglich → der Vote ist terminal quorum-verfehlt und
        # wird über den ``fail``-Branch geschlossen (statt ewig blockiert).
        if not outcome.quorum_met and not window_expired:
            raise ConflictError(
                "quorum not met — the vote cannot be closed; collect more ballots "
                "or cancel the vote.",
                code="conflict",
            )

        # Verfallenes Quorum: »rejected« erzwingen → fail-Branch (s. ``branch_name``).
        result_value: tally_mod.VoteResult = (
            outcome.result if outcome.quorum_met else "rejected"
        )

        # Global-Flow (#28): ein ``vote``-State hat zwei feste Ausgänge mit ``branch``
        # ``pass``/``fail``. ``passed`` → pass, sonst (``rejected``/``tie``) fail-closed
        # → fail. Generische Beschlussfragen (ohne Antrag) feuern KEINEN Branch — sie
        # halten nur das Ergebnis fürs Protokoll.
        branch_name = "pass" if result_value == "passed" else "fail"
        flow = FlowService(self.session, self.dispatcher)
        branch = (
            await flow.branch_transition(vote.application_id, branch_name)
            if vote.application_id is not None
            else None
        )
        # Antragsgebundener Vote OHNE passenden Branch-Übergang (fehlkonfigurierter
        # Flow / Vote auf einem Nicht-``vote``-State): fail-closed statt still schließen,
        # sonst stünde das Ergebnis fest, der Antrag bliebe aber ewig im Vor-Vote-State.
        if vote.application_id is not None and branch is None:
            raise ConflictError(
                f"no '{branch_name}' branch transition for the vote's current state; "
                "flow is misconfigured.",
                code="conflict",
            )

        # Vote-Zustand vormerken — NICHT separat committen: `fire` schreibt ihn
        # atomar mit Transition + status_event; ohne Branch committen wir hier.
        vote.status = "closed"
        vote.result = result_value
        vote.result_branch_transition_id = branch.id if branch is not None else None

        new_state_id: UUID | None = None
        if branch is not None and vote.application_id is not None:
            fired = await flow.fire_branch(
                vote.application_id, branch_name, principal, note=f"vote:{result_value}"
            )
            new_state_id = fired.new_state_id
        else:
            await self.session.commit()

        tally_out = TallyOut(
            counts=counts,
            eligible=eligible,
            quorumMet=outcome.quorum_met,
            leading=outcome.leading,
            result=result_value,
            failedReason=tally_mod.failed_reason(result_value, outcome.quorum_met),
        )
        return VoteClosed(
            id=vote.id,
            meetingId=vote.meeting_id,
            result=result_value,
            tally=tally_out,
            firedTransitionId=branch.id if branch is not None else None,
            newStateId=new_state_id,
        )
