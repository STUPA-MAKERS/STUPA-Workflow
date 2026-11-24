"""The access checks of the routes and the reads of a protocol and its PDFs."""

from __future__ import annotations

from uuid import UUID

from app.modules.auth.principal import Principal
from app.modules.files.storage import StorageError
from app.modules.meetings.models import Meeting
from app.modules.protocol.filename import protocol_pdf_filename
from app.modules.protocol.public import meeting_day
from app.modules.protocol.schemas import ProtocolOut
from app.modules.protocol.service.base import ProtocolServiceBase
from app.shared.errors import ForbiddenError, NotFoundError, ServiceUnavailableError


class ReadOps(ProtocolServiceBase):
    """Authorization and reads."""

    async def authorize_write_meeting(self, meeting_id: UUID, principal: Principal) -> None:
        """Check the write access to the protocol of a meeting (create or load).

        One of these rights is enough: the admin role, the Gremium permission
        `session.manage`, the assigned protokollant role, or a Gremium role with
        `protocol.write`. The rule is the same as `can_write`.

        Raises:
            ForbiddenError: The principal must not write the minutes of this meeting.
        """
        meeting = await self._meeting(meeting_id)
        if not await self._meeting_service().can_write(meeting, principal):
            raise ForbiddenError("not allowed to write this meeting's minutes")

    async def authorize_write(self, protocol_id: UUID, principal: Principal) -> None:
        """Check the write access to an existing protocol (PATCH or embed votes)."""
        protocol = await self._get(protocol_id)
        await self.authorize_write_meeting(protocol.meeting_id, principal)

    async def authorize_finalize(self, protocol_id: UUID, principal: Principal) -> None:
        """Check the right to finalize and send a protocol.

        The caller needs the write access AND the Gremium permission
        `protocol.finalize` in the Gremium of the meeting (or the admin role). This
        rule is stricter than the rule for a draft write. `MeetingService.can_finalize`
        holds the rule, so the `canFinalize` flag of the meeting agrees with it.

        Raises:
            ForbiddenError: The caller has no write access or lacks
                `protocol.finalize`.
        """
        protocol = await self._get(protocol_id)
        meeting = await self._meeting(protocol.meeting_id)
        svc = self._meeting_service()
        if not await svc.can_write(meeting, principal):
            raise ForbiddenError("not allowed to write this meeting's minutes")
        if not await svc.can_finalize(meeting, principal):
            raise ForbiddenError("Missing permission(s): protocol.finalize")

    async def authorize_read(self, protocol_id: UUID, principal: Principal) -> None:
        """Check the read access with the meeting visibility rule `assert_can_read`."""
        protocol = await self._get(protocol_id)
        await self._meeting_service().assert_can_read(protocol.meeting_id, principal)

    async def authorize_read_meeting(self, meeting_id: UUID, principal: Principal) -> None:
        """Check the read access to the protocol of a meeting (GET …/protocol)."""
        await self._meeting_service().assert_can_read(meeting_id, principal)

    async def get_pdf_bytes(self, protocol_id: UUID) -> bytes:
        """Fetch the PDF bytes of the protocol from storage for the `/pdf` stream.

        Raises:
            NotFoundError: The protocol is missing, no PDF is rendered yet, or
                storage is off (404).
            ServiceUnavailableError: The storage failed for a short time (503). The
                caller can repeat the call.
        """
        protocol = await self._get(protocol_id)
        if protocol.pdf_storage_key is None or self.storage is None:
            raise NotFoundError(f"protocol {protocol_id} has no PDF")
        try:
            return await self.storage.get(protocol.pdf_storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Protocol PDF temporarily unavailable.") from exc

    async def pdf_filename(self, protocol_id: UUID, *, public: bool = False) -> str:
        """Return the download name of the protocol PDF: meeting title and day.

        Args:
            protocol_id: The protocol.
            public: `True` for the redacted variant (`_oeffentlich`).

        Raises:
            NotFoundError: The protocol or its meeting is missing (404).
        """
        protocol = await self._get(protocol_id)
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        if meeting is None:
            raise NotFoundError(f"protocol {protocol_id} has no meeting")
        return protocol_pdf_filename(meeting.title, meeting_day(meeting), public=public)

    async def get_public_pdf_bytes(self, protocol_id: UUID) -> bytes:
        """Fetch the bytes of the redacted public variant for the `/pdf/public` stream."""
        protocol = await self._get(protocol_id)
        if protocol.public_pdf_storage_key is None or self.storage is None:
            raise NotFoundError(f"protocol {protocol_id} has no public PDF")
        try:
            return await self.storage.get(protocol.public_pdf_storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Protocol PDF temporarily unavailable.") from exc

    async def get_by_meeting(self, meeting_id: UUID) -> ProtocolOut:
        """Read the protocol of a meeting on the reload and poll path.

        This method has no create side effect, by design. The frontend polls during
        the background render. A GET is not subject to the write rate limit.

        Raises:
            NotFoundError: The meeting has no protocol (404).
        """
        protocol = await self._by_meeting(meeting_id)
        if protocol is None:
            raise NotFoundError(f"protocol for meeting {meeting_id} not found")
        return await self._to_out(protocol)
