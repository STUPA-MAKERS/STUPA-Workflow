"""The file operations that read an application.

`AttachmentService` is the files service plus the operations that read the application
of a file: the upload to an application, the list of an application, the download of an
application file and the edit lock. These operations are here and not in `files`,
because `files` imports no higher module (§S/backend/python/000651).

``signed_url`` returns the app-relative ``/download`` route that the authorization layer
gates. It does so only after a clean scan. The route carries no signature and does not
expire. While the scan runs the method answers 409. After a removal it answers 410. There
is no direct bucket access.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from sqlalchemy import select

from app.modules.applications.models import Application
from app.modules.files.models import BOUND, Attachment
from app.modules.files.schemas import AttachmentOut, SignedUrlOut
from app.modules.files.service import FilesService, application_id_of, attachment_out
from app.modules.flow.models import State
from app.shared.errors import ConflictError, NotFoundError


@dataclass(frozen=True, slots=True)
class AttachmentService(FilesService):
    """The files service plus the operations that read an application."""

    async def upload(
        self,
        application_id: uuid.UUID,
        *,
        filename: str | None,
        data: bytes,
        by: str,
        field_key: str | None = None,
    ) -> AttachmentOut:
        """Upload a file to an application that exists (see ``FilesService.upload``).

        Raises:
            NotFoundError: No application has this id (HTTP 404).
        """
        if await self.session.get(Application, application_id) is None:
            raise NotFoundError(f"application {application_id} not found")
        return await FilesService.upload(
            self, application_id, filename=filename, data=data, by=by, field_key=field_key
        )

    async def assert_app_visible(
        self, application_id: uuid.UUID, *, allow_unconfirmed: bool
    ) -> None:
        """Mirror the visibility of the application.

        An unconfirmed guest submission has ``email_confirmed_at IS NULL``. It stays
        invisible to a principal or a member of the Gremium, exactly as
        ``list_applications`` and ``list_tasks`` hide it.

        An item route without an owning magic-link applicant passes
        ``allow_unconfirmed=False``. It then gets 404 instead of 403, so the API is no
        existence oracle. This mirrors the application detail, timeline, version and
        comment gates. The owning applicant reads with the default
        ``allow_unconfirmed=True``.

        Raises:
            NotFoundError: The application is an unconfirmed guest submission and
                ``allow_unconfirmed`` is false.
        """
        if allow_unconfirmed:
            return
        confirmed = await self.session.scalar(
            select(Application.email_confirmed_at).where(Application.id == application_id)
        )
        if confirmed is None:
            raise NotFoundError(f"application {application_id} not found")

    async def list_for_application(
        self,
        application_id: uuid.UUID,
        *,
        allow_unconfirmed: bool = True,
        hidden: Callable[[Attachment], bool] | None = None,
    ) -> list[AttachmentOut]:
        """Return all attachments of an application, oldest first.

        The frontend uses this for the panel after a reload.

        A read by a principal or a member of the Gremium passes
        ``allow_unconfirmed=False``. The method then hides the attachments of an
        unconfirmed guest submission with a 404. This mirrors the list semantics.

        ``hidden`` removes each attachment for which it returns true. The router
        uses it for the attachments of the ``isPII`` fields.
        """
        await self.assert_app_visible(application_id, allow_unconfirmed=allow_unconfirmed)
        rows = (
            await self.session.scalars(
                select(Attachment)
                .where(BOUND, Attachment.application_id == application_id)
                .order_by(Attachment.created_at)
            )
        ).all()
        return [attachment_out(a) for a in rows if hidden is None or not hidden(a)]

    async def signed_url(
        self, attachment_id: uuid.UUID, *, allow_unconfirmed: bool = True
    ) -> SignedUrlOut:
        """Return the app-relative download URL after a clean scan.

        Any other state gives 409, 410 or 503.

        The route is no presigned MinIO URL. MinIO runs on the internal Docker network
        and publishes no port. An S3v4 signature binds the internal host, so the browser
        cannot reach such a URL. The ``/download`` endpoint streams the bytes from the
        server through nginx under ``/api/`` instead.

        A read by a principal or a member of the Gremium passes
        ``allow_unconfirmed=False``. An unconfirmed guest submission then gives 404,
        which mirrors the list semantics. The visibility gate runs BEFORE the quarantine
        gates. A hidden application must not shine through as existing over 409, 410
        or 503.
        """
        attachment = await self.get_attachment(attachment_id)
        await self.assert_app_visible(
            application_id_of(attachment), allow_unconfirmed=allow_unconfirmed
        )
        await self.ready_attachment(attachment_id)
        return SignedUrlOut(
            url=f"/api/attachments/{attachment_id}/download",
            expiresIn=self.settings.attachment_url_ttl_seconds,
        )

    async def download_stream(
        self, attachment_id: uuid.UUID, *, allow_unconfirmed: bool = True
    ) -> tuple[AsyncIterator[bytes], str, str, int]:
        """Return a chunk iterator over the attachment bytes for the ``/download`` stream.

        The quarantine gates (409, 410, 503) and the visibility gate run unchanged BEFORE
        the stream starts. The method opens the storage connection eagerly, so a
        transient error still surfaces as 503 before the response header goes out.

        A read by a principal or a member of the Gremium passes
        ``allow_unconfirmed=False``. An unconfirmed guest submission then gives 404,
        which mirrors the list semantics.

        Returns:
            The iterator, the filename, the MIME type and the size. The caller puts the
            size into ``Content-Length``.
        """
        loaded = await self.get_attachment(attachment_id)
        await self.assert_app_visible(
            application_id_of(loaded), allow_unconfirmed=allow_unconfirmed
        )
        return await self.open_stream(await self.ready_attachment(attachment_id))

    async def assert_editable(self, application_id: uuid.UUID) -> None:
        """Make sure that the current state of the application allows data edits.

        The router calls this before an applicant or a creator deletes an attachment.
        A delete is a data change, like a PATCH. An upload is not, so the upload route
        does not call it. An application without a state passes.

        Raises:
            ConflictError: The current state has ``edit_allowed = false`` (HTTP 409).
        """
        edit_allowed = await self.session.scalar(
            select(State.edit_allowed)
            .join(Application, Application.current_state_id == State.id)
            .where(Application.id == application_id)
        )
        if edit_allowed is False:
            raise ConflictError(
                "Application is locked for editing in its current state.",
                code="application_locked",
            )
