"""Budget-Service (T-17): Topf-CRUD, Antrag→Topf-Zuordnung, Lebenszyklus, Statistik.

Dünne I/O-Verdrahtung; die Entscheidungslogik liegt rein in :mod:`app.modules.budget.rules`
(testing.md §1: ``budget`` = kritisches Modul → 100 % Branch). Geld als ``Decimal``;
Reservier-/Buch-Stufen prüfen Überbuchung (``budget_pot.total``) fail-closed.

Töpfe tragen Extra-Felder (= ``FormFieldDef``, §5.7); diese fließen über die
T-11-``effective_form`` in den Antrag (nur bei Topf-Zuordnung). Anträge **ohne** Topf
bleiben unberührt voll funktionsfähig (kein ``budget_entry``).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.budget import rules
from app.modules.budget.models import BudgetEntry, BudgetField, BudgetPot
from app.modules.budget.schemas import (
    AssignOut,
    AssignRequest,
    BudgetPotCreate,
    BudgetPotDetailOut,
    BudgetPotOut,
    BudgetPotUpdate,
    PotUsageOut,
)
from app.modules.budget.stats import BudgetStatsService
from app.modules.forms.validation import FormDefinitionError, validate_definition
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

# Hook, der eine MV-Rollup-Aktualisierung anstößt (Worker-Enqueue). Default: keiner
# (Service bleibt rein); der Router verdrahtet den realen arq-Enqueue.
StatsRefreshHook = Callable[[], Awaitable[None]]


def _checked_amount(amount: Decimal | None) -> Decimal | None:
    """Promoted ``amount`` defensiv prüfen: ``None`` ok (budgetlos), sonst muss er
    endlich sein. NaN/Infinity (fehlerhafte Promotion aus T-12) würde sonst still gegen
    ``budget_pot.total`` gerechnet und den Überbuchungsschutz aushebeln → 422."""
    if amount is not None and not amount.is_finite():
        raise ValidationProblem(
            "Promoted amount is not finite.",
            errors=[{"field": "amount", "msg": "must be a finite number"}],
        )
    return amount


class BudgetService:
    """DB-gestützte Budget-Operationen (an eine ``AsyncSession`` gebunden)."""

    def __init__(
        self, session: AsyncSession, *, stats_refresh: StatsRefreshHook | None = None
    ) -> None:
        self.session = session
        self._stats_refresh = stats_refresh

    # ------------------------------------------------------------ low-level gets
    async def _get_pot(self, pot_id: UUID, *, for_update: bool = False) -> BudgetPot:
        """Topf laden; ``for_update`` sperrt die Zeile (``SELECT … FOR UPDATE``).

        Die Sperre serialisiert nebenläufige Reservierungen auf denselben Topf, sodass
        der Überbuchungs-Check (``would_overbook``) den Verbrauch des jeweils anderen
        sieht statt einer veralteten Summe (READ COMMITTED) — DB-Backstop gegen die
        Über-Allokations-Race.
        """
        stmt = select(BudgetPot).where(BudgetPot.id == pot_id)
        if for_update:
            stmt = stmt.with_for_update()
        pot = (await self.session.execute(stmt)).scalar_one_or_none()
        if pot is None:
            raise NotFoundError(f"budget pot {pot_id} not found")
        return pot

    async def _get_application(self, application_id: UUID) -> Application:
        app = (
            await self.session.execute(
                select(Application).where(Application.id == application_id)
            )
        ).scalar_one_or_none()
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    async def _get_type(self, type_id: UUID) -> ApplicationType:
        app_type = (
            await self.session.execute(
                select(ApplicationType).where(ApplicationType.id == type_id)
            )
        ).scalar_one_or_none()
        if app_type is None:
            raise NotFoundError(f"application type {type_id} not found")
        return app_type

    async def _get_entry(self, application_id: UUID) -> BudgetEntry | None:
        return (
            await self.session.execute(
                select(BudgetEntry).where(BudgetEntry.application_id == application_id)
            )
        ).scalar_one_or_none()

    async def _fields_of_pot(self, pot_id: UUID) -> list[FormFieldDef]:
        rows = (
            await self.session.execute(
                select(BudgetField)
                .where(BudgetField.budget_pot_id == pot_id)
                .order_by(BudgetField.order)
            )
        ).scalars().all()
        return [FormFieldDef.model_validate(r.field) for r in rows]

    async def _trigger_refresh(self) -> None:
        """MV-Rollup-Refresh anstoßen, falls ein Hook injiziert ist (sonst No-op)."""
        if self._stats_refresh is not None:
            await self._stats_refresh()

    @staticmethod
    def _pot_out(pot: BudgetPot, fields: list[FormFieldDef]) -> BudgetPotOut:
        return BudgetPotOut(
            id=pot.id,
            gremiumId=pot.gremium_id,
            name=pot.name,
            total=pot.total,
            currency=pot.currency,
            period=pot.period,
            active=pot.active,
            fields=fields,
        )

    @staticmethod
    def _validate_fields(fields: list[FormFieldDef]) -> None:
        """Extra-Feld-Defs strukturell prüfen (Whitelist/kein eval, §5.1) → 422."""
        try:
            validate_definition(fields)
        except FormDefinitionError as exc:
            raise ValidationProblem(
                "Invalid budget field definition.",
                errors=[{"field": "fields", "msg": str(exc)}],
            ) from exc

    # --------------------------------------------------------------- pot CRUD
    async def create_pot(self, payload: BudgetPotCreate) -> BudgetPotOut:
        """Topf + optionale Extra-Felder anlegen. Gremium muss existieren."""
        self._validate_fields(payload.fields)
        gremium = (
            await self.session.execute(
                select(Gremium).where(Gremium.id == payload.gremium_id)
            )
        ).scalar_one_or_none()
        if gremium is None:
            raise NotFoundError(f"gremium {payload.gremium_id} not found")

        pot = BudgetPot(
            id=uuid.uuid4(),
            gremium_id=payload.gremium_id,
            name=payload.name,
            total=payload.total,
            currency=payload.currency,
            period=payload.period,
            active=payload.active,
        )
        self.session.add(pot)
        await self.session.flush()  # Topf zuerst persistieren (FK budget_field→pot).
        for order, field in enumerate(payload.fields):
            self.session.add(
                BudgetField(
                    id=uuid.uuid4(),
                    budget_pot_id=pot.id,
                    field=field.model_dump(by_alias=True, exclude_none=True),
                    order=order,
                )
            )
        await self.session.commit()
        return self._pot_out(pot, list(payload.fields))

    async def list_pots(
        self,
        *,
        gremium_id: UUID | None = None,
        period: str | None = None,
        active: bool | None = None,
    ) -> list[BudgetPotOut]:
        """Töpfe gefiltert auflisten (+ Extra-Felder je Topf)."""
        filters = []
        if gremium_id is not None:
            filters.append(BudgetPot.gremium_id == gremium_id)
        if period is not None:
            filters.append(BudgetPot.period == period)
        if active is not None:
            filters.append(BudgetPot.active.is_(active))
        pots = (
            await self.session.execute(
                select(BudgetPot).where(*filters).order_by(BudgetPot.name)
            )
        ).scalars().all()
        out: list[BudgetPotOut] = []
        for pot in pots:
            out.append(self._pot_out(pot, await self._fields_of_pot(pot.id)))
        return out

    async def get_pot(self, pot_id: UUID) -> BudgetPotDetailOut:
        """Einzelnen Topf + live berechnete Auslastung liefern."""
        pot = await self._get_pot(pot_id)
        fields = await self._fields_of_pot(pot_id)
        usage = await self._live_usage(pot)
        return BudgetPotDetailOut(pot=self._pot_out(pot, fields), usage=usage)

    async def update_pot(self, pot_id: UUID, payload: BudgetPotUpdate) -> BudgetPotOut:
        """Topf teil-aktualisieren; ``fields`` (falls gesetzt) ersetzt die Extra-Felder."""
        pot = await self._get_pot(pot_id)
        provided = payload.model_dump(exclude_unset=True)
        new_fields = provided.pop("fields", None)
        for key, value in provided.items():
            setattr(pot, key, value)
        fields = await self._fields_of_pot(pot_id)
        if new_fields is not None:
            parsed = [FormFieldDef.model_validate(f) for f in new_fields]
            self._validate_fields(parsed)
            await self.session.execute(
                delete(BudgetField).where(BudgetField.budget_pot_id == pot_id)
            )
            for order, field in enumerate(parsed):
                self.session.add(
                    BudgetField(
                        id=uuid.uuid4(),
                        budget_pot_id=pot_id,
                        field=field.model_dump(by_alias=True, exclude_none=True),
                        order=order,
                    )
                )
            fields = parsed
        await self.session.commit()
        return self._pot_out(pot, fields)

    # ------------------------------------------------------------- assignment
    async def assign(
        self, application_id: UUID, payload: AssignRequest, *, actor: str
    ) -> AssignOut:
        """Antrag einem Topf zuordnen (manuell). ``budgetPotId=null`` löst die Zuordnung.

        Setzbar nur bei ``type.has_budget`` und passendem Gremium (data-model §2,
        fail-closed). Erzeugt/aktualisiert den ``requested``-``budget_entry`` aus dem
        promoted ``amount``.
        """
        app = await self._get_application(application_id)
        entry = await self._get_entry(application_id)

        if payload.budget_pot_id is None:
            app.budget_pot_id = None
            if entry is not None:
                await self.session.delete(entry)
            await self.session.commit()
            await self._trigger_refresh()
            return AssignOut(
                applicationId=app.id,
                gremiumId=app.gremium_id,
                budgetPotId=None,
                stage=None,
                amount=None,
                currency=None,
            )

        app_type = await self._get_type(app.type_id)
        pot = await self._get_pot(payload.budget_pot_id)
        reason = rules.assignment_block_reason(
            has_budget=app_type.has_budget,
            type_gremium_id=app_type.gremium_id,
            pot_gremium_id=pot.gremium_id,
        )
        if reason is not None:
            raise ValidationProblem(reason, errors=[{"field": "budgetPotId", "msg": reason}])

        app.budget_pot_id = pot.id
        app.gremium_id = pot.gremium_id
        currency = app.currency or pot.currency
        if entry is None:
            entry = BudgetEntry(id=uuid.uuid4(), application_id=application_id)
            self.session.add(entry)
        entry.budget_pot_id = pot.id
        entry.stage = "requested"
        entry.amount = _checked_amount(app.amount)
        entry.currency = currency
        entry.actor = actor
        entry.note = payload.note
        await self.session.commit()
        await self._trigger_refresh()
        return AssignOut(
            applicationId=app.id,
            gremiumId=pot.gremium_id,
            budgetPotId=pot.id,
            stage="requested",
            amount=entry.amount,
            currency=currency,
        )

    # ------------------------------------------------------------- lifecycle
    async def set_stage(
        self, application_id: UUID, target: str, *, actor: str, note: str | None = None
    ) -> AssignOut:
        """Budget-Entry auf ``target`` vorrücken (SDS-A1). Überbuchung → 409.

        Nur Vorwärtsbewegung entlang :data:`STAGES`; bindende Stufen (reserved/approved/
        paid) prüfen, dass ``budget_pot.total`` nicht überbucht wird (fail-closed).
        """
        entry = await self._get_entry(application_id)
        if entry is None:
            raise NotFoundError(
                f"application {application_id} has no budget assignment"
            )
        if not rules.can_advance(entry.stage, target):
            raise ConflictError(
                f"cannot advance budget stage from {entry.stage!r} to {target!r}"
            )
        app = await self._get_application(application_id)
        entry.amount = _checked_amount(app.amount)
        # Jede Vorwärts-Stufe (reserved/approved/paid) bindet Budget → Überbuchung
        # prüfen (``requested`` ist nie ein Vorwärtsziel, daher kein Sonderzweig).
        # FOR UPDATE: Topf-Zeile sperren, damit der Verbrauch konsistent gelesen wird
        # (serialisiert nebenläufige Reservierungen, kein Über-Allokations-Race).
        pot = await self._get_pot(entry.budget_pot_id, for_update=True)
        committed_others = await self._committed_excluding(
            entry.budget_pot_id, application_id
        )
        if rules.would_overbook(pot.total, committed_others, entry.amount):
            raise ConflictError("reservation would exceed the budget pot total")
        entry.stage = target
        entry.actor = actor
        if note is not None:
            entry.note = note
        await self.session.commit()
        await self._trigger_refresh()
        return AssignOut(
            applicationId=application_id,
            gremiumId=app.gremium_id,
            budgetPotId=entry.budget_pot_id,
            stage=target,  # type: ignore[arg-type] — gegen STAGES via can_advance geprüft
            amount=entry.amount,
            currency=entry.currency,
        )

    async def reserve(
        self, application_id: UUID, *, actor: str, note: str | None = None
    ) -> AssignOut:
        """Bequemer Wrapper: Stufe ``reserved`` (Flow-Action ``budgetReserve``)."""
        return await self.set_stage(application_id, "reserved", actor=actor, note=note)

    async def book(
        self, application_id: UUID, *, actor: str, note: str | None = None
    ) -> AssignOut:
        """Bequemer Wrapper: Stufe ``approved`` (Flow-Action ``budgetBook``)."""
        return await self.set_stage(application_id, "approved", actor=actor, note=note)

    # --------------------------------------------------------------- usage
    async def _entries_of_pot(self, pot_id: UUID) -> list[BudgetEntry]:
        return list(
            (
                await self.session.execute(
                    select(BudgetEntry).where(BudgetEntry.budget_pot_id == pot_id)
                )
            ).scalars().all()
        )

    async def _committed_excluding(
        self, pot_id: UUID, application_id: UUID
    ) -> Decimal:
        entries = await self._entries_of_pot(pot_id)
        total = rules.as_amount(None)
        for e in entries:
            if e.application_id != application_id and rules.is_committed(e.stage):
                total += rules.as_amount(e.amount)
        return total

    async def _live_usage(self, pot: BudgetPot) -> PotUsageOut:
        entries = await self._entries_of_pot(pot.id)
        stage_sums: dict[str, Decimal] = {}
        for e in entries:
            stage_sums[e.stage] = rules.as_amount(stage_sums.get(e.stage)) + rules.as_amount(
                e.amount
            )
        usage = rules.usage_from_stage_sums(stage_sums, pot.total)
        return PotUsageOut(
            budgetPotId=pot.id,
            period=pot.period,
            total=pot.total,
            currency=pot.currency,
            requested=usage.requested,
            reserved=usage.reserved,
            approved=usage.approved,
            paid=usage.paid,
            committed=usage.committed,
            available=usage.available,
        )

    # --------------------------------------------------------------- stats
    def stats_service(self) -> BudgetStatsService:
        return BudgetStatsService(self.session)
