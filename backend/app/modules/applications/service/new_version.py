"""New versions of an Antrag ("Neue Fassung", specs 001720-001722).

A denied Antrag, or one that a Gremium returned into an editable state, gets a new
version: a new draft of the same type with the answers that the prefill of a
Folgeantrag copies (`LinkOps.prefill`), and without files. The new draft names the old
Antrag in ``replaces_id``. The flow closes the old Antrag when the new version is
submitted (`FlowService._close_replaced`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.modules.applications.models import Applicant, Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service.create import CreateOps, NewVersion
from app.modules.applications.service.links import LinkOps
from app.modules.flow.models import State
from app.shared.errors import ConflictError

if TYPE_CHECKING:
    from app.modules.flow.dispatch import ActionDispatcher

#: The error code of an Antrag that offers no new version.
NEW_VERSION_NOT_ALLOWED = "new_version_not_allowed"


def offers_new_version(state: State | None) -> bool:
    """Tell whether an Antrag in ``state`` offers a new version.

    That is a denied state, or an editable state that is not the initial state: a
    Gremium returned the Antrag to the applicant.
    """
    return state is not None and (state.is_denied or (state.edit_allowed and not state.is_initial))


class NewVersionOps(CreateOps, LinkOps):
    """Create the new version of an Antrag."""

    async def new_version(
        self,
        application_id: UUID,
        *,
        actor: str,
        hidden: set[str],
        dispatcher: ActionDispatcher | None = None,
    ) -> tuple[Application, str]:
        """Create a new draft that replaces the Antrag ``application_id``.

        The draft has the type, the applicant, the owner and the language of the old
        Antrag, and the answers of `LinkOps.prefill` without the keys in ``hidden``.
        The create runs as for a submission, so it writes version 1, the initial state
        and the audit entry, and starts the flow.

        Returns:
            The new Antrag and the e-mail address of its applicant.

        Raises:
            NotFoundError: The Antrag does not exist (404).
            ConflictError: The state of the Antrag offers no new version, or its
                applicant is anonymized (409 ``new_version_not_allowed``).
        """
        old = await self._get_app(application_id, allow_unconfirmed=False)
        state = (
            await self.session.get(State, old.current_state_id)
            if old.current_state_id is not None
            else None
        )
        applicant = await self.session.scalar(
            select(Applicant).where(Applicant.application_id == old.id)
        )
        if not offers_new_version(state) or applicant is None or applicant.email is None:
            raise ConflictError("This Antrag offers no new version.", code=NEW_VERSION_NOT_ALLOWED)
        prefill = await self.prefill(old.id, hidden=hidden)
        payload = ApplicationCreate.model_validate(
            {
                "typeId": old.type_id,
                "data": prefill.data,
                "applicantEmail": applicant.email,
                "applicantName": applicant.name,
                **({"lang": old.lang} if old.lang else {}),
            }
        )
        return await self.create(
            payload,
            actor=actor,
            dispatcher=dispatcher,
            email_confirmed=True,
            new_version=NewVersion(owner_sub=old.created_by, replaces_id=old.id),
        )
