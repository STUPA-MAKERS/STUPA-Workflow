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
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
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


class VotingService:
    """An eine ``AsyncSession`` (+ optionalen Flow-Dispatcher) gebundener Service."""

    def __init__(
        self, session: AsyncSession, dispatcher: ActionDispatcher | None = None
    ) -> None:
        self.session = session
        self.dispatcher: ActionDispatcher = dispatcher or NullActionDispatcher()

    # ----------------------------------------------------------------- helpers
    async def _get_vote(self, vote_id: UUID) -> Vote:
        vote = (
            await self.session.execute(select(Vote).where(Vote.id == vote_id))
        ).scalar_one_or_none()
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        return vote

    async def _get_application(self, application_id: UUID) -> Application:
        app = (
            await self.session.execute(
                select(Application).where(Application.id == application_id)
            )
        ).scalar_one_or_none()
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    @staticmethod
    def _config(vote: Vote) -> VoteConfig:
        return VoteConfig.model_validate(vote.config)

    async def _count_eligible(self, eligible_group: str) -> int:
        """Stimmberechtigte = Principals, deren OIDC-Gruppen den Key enthalten.

        Dokumentierte Scope-Grenze (SDS-A3): gezählt werden OIDC-Gruppen-Mitglieder
        (``principal.oidc_groups``); Gremium-Rollen-Feinsteuerung ist Folge-Arbeit."""
        count = (
            await self.session.execute(
                select(func.count())
                .select_from(PrincipalRow)
                .where(PrincipalRow.oidc_groups.contains([eligible_group]))
            )
        ).scalar_one()
        return int(count)

    async def _aggregate(self, vote: Vote, config: VoteConfig) -> dict[str, int]:
        """Stimmen je Option zählen — offen aus ``ballot``, geheim aus ``secret_ballot``."""
        if config.secret:
            choices: Sequence[str | None] = (
                await self.session.execute(
                    select(SecretBallot.choice).where(SecretBallot.vote_id == vote.id)
                )
            ).scalars().all()
        else:
            choices = (
                await self.session.execute(
                    select(Ballot.choice).where(Ballot.vote_id == vote.id)
                )
            ).scalars().all()
        return tally_mod.tally(config.options, choices)

    def _tally_out(
        self, config: VoteConfig, counts: dict[str, int], eligible: int
    ) -> TallyOut:
        outcome = tally_mod.result(config, counts, eligible)
        return TallyOut(
            counts=counts,
            eligible=eligible,
            quorumMet=outcome.quorum_met,
            leading=outcome.leading,
            result=None,
        )

    def _to_out(self, vote: Vote, config: VoteConfig, tally_out: TallyOut) -> VoteOut:
        return VoteOut(
            id=vote.id,
            applicationId=vote.application_id,
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
    async def create(self, application_id: UUID, payload: VoteCreate) -> VoteOut:
        """Abstimmung (``draft``) anlegen. 404, wenn der Antrag fehlt."""
        await self._get_application(application_id)
        vote = Vote(
            application_id=application_id,
            eligible_group=payload.eligible_group,
            config=payload.config.model_dump(by_alias=True),
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
        return self._to_out(vote, config, self._tally_out(config, empty, 0))

    # ----------------------------------------------------------------- open
    async def open(self, vote_id: UUID, *, now: datetime) -> VoteOut:
        """``draft`` → ``open``: Stimmberechtigte zählen + ``opens_at`` setzen."""
        vote = await self._get_vote(vote_id)
        if vote.status != "draft":
            raise ConflictError(
                f"vote is {vote.status}, cannot open.", code="conflict"
            )
        config = self._config(vote)
        vote.eligible_count = await self._count_eligible(vote.eligible_group)
        vote.opens_at = now
        vote.status = "open"
        await self.session.flush()
        await self.session.commit()
        empty = {opt: 0 for opt in config.options}
        return self._to_out(vote, config, self._tally_out(config, empty, vote.eligible_count))

    # ----------------------------------------------------------------- cast
    async def cast(
        self,
        vote_id: UUID,
        principal: Principal,
        choice: str,
        *,
        now: datetime,
    ) -> BallotAccepted:
        """Stimme abgeben. 409 (geschlossen/Doppel), 403 (nicht stimmberechtigt),
        422 (unbekannte Option)."""
        vote = await self._get_vote(vote_id)
        if vote.status != "open":
            raise ConflictError("vote is not open.", code="conflict")
        if vote.closes_at is not None and now >= vote.closes_at:
            raise ConflictError("voting window has closed.", code="conflict")
        if not principal.in_group(vote.eligible_group):
            raise ForbiddenError("Not eligible to vote in this ballot.")
        config = self._config(vote)
        if choice not in config.options:
            raise ValidationProblem(
                "Unknown vote option.",
                errors=[{"field": "choice", "msg": "not in vote options"}],
            )
        if config.secret:
            return await self._cast_secret(vote.id, principal.sub, choice)
        return await self._cast_open(vote.id, principal.sub, choice, config.allow_change)

    async def _cast_open(
        self, vote_id: UUID, voter_sub: str, choice: str, allow_change: bool
    ) -> BallotAccepted:
        values = {"vote_id": vote_id, "voter_sub": voter_sub, "choice": choice}
        if allow_change:
            stmt = (
                pg_insert(Ballot)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_ballot_vote_voter",
                    set_={"choice": choice, "at": func.now()},
                )
                .returning(Ballot.id)
            )
            await self.session.execute(stmt)
            await self.session.commit()
            return BallotAccepted(status="changed")

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

    async def _cast_secret(
        self, vote_id: UUID, voter_sub: str, choice: str
    ) -> BallotAccepted:
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
    async def get(self, vote_id: UUID) -> VoteOut:
        """Vote-State + aggregiertes Tally (geheim: nur counts, nie Wähler)."""
        vote = await self._get_vote(vote_id)
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        tally_out = self._tally_out(config, counts, vote.eligible_count)
        if vote.status == "closed" and vote.result is not None:
            tally_out = tally_out.model_copy(update={"result": vote.result})
        return self._to_out(vote, config, tally_out)

    # ----------------------------------------------------------------- close
    async def close(self, vote_id: UUID, principal: Principal) -> VoteClosed:
        """``open`` → ``closed``: auszählen → Ergebnis → ``flow.fire(result_branch)``."""
        vote = await self._get_vote(vote_id)
        if vote.status != "open":
            raise ConflictError(
                f"vote is {vote.status}, cannot close.", code="conflict"
            )
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        outcome = tally_mod.result(config, counts, vote.eligible_count)

        vote.status = "closed"
        vote.result = outcome.result
        await self.session.flush()
        await self.session.commit()

        tally_out = TallyOut(
            counts=counts,
            eligible=vote.eligible_count,
            quorumMet=outcome.quorum_met,
            leading=outcome.leading,
            result=outcome.result,
        )
        fired_id, new_state_id = await self._fire_branch(
            vote, outcome.result, principal
        )
        return VoteClosed(
            id=vote.id,
            result=outcome.result,
            tally=tally_out,
            firedTransitionId=fired_id,
            newStateId=new_state_id,
        )

    async def _fire_branch(
        self, vote: Vote, vote_result: str, principal: Principal
    ) -> tuple[UUID | None, UUID | None]:
        """Den zum Ergebnis passenden ``voteResult``-Übergang feuern (flows §3/§4).

        Wählt unter den verfügbaren Übergängen (Guards mit ``vote_result`` erfüllt) den
        ersten und feuert ihn. Gibt es keinen, bleibt es beim Schließen ohne Branch."""
        flow = FlowService(self.session, self.dispatcher)
        available = await flow.available_transitions(
            vote.application_id, principal, vote_result=vote_result
        )
        if not available:
            return None, None
        transition_id = available[0].id
        result = await flow.fire(
            vote.application_id,
            transition_id,
            principal,
            vote_result=vote_result,
        )
        return transition_id, result.new_state_id
