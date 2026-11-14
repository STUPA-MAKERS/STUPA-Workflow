"""The PDF export of an Antrag: `GET /api/applications/{id}/pdf`.

Each person who can read the Antrag downloads it: a member with the read right, the
applicant, an observer and the creator (spec 000880). The route reads through the same
gate as the detail page (`require_app_view`), and the PDF shows the same fields
(spec 000882). The PDF streams through the API and never through a presigned URL,
because MinIO has no browser access.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from app.deps import DbSession, SettingsDep
from app.modules.applications.access import Access, require_app_view
from app.modules.applications.service import ApplicationsService
from app.modules.documents.service import ApplicationPdfService
from app.modules.files.storage import ObjectStorage
from app.modules.pdf.typst_client import build_typst_client
from app.shared.errors import ProblemDetail
from app.shared.filenames import content_disposition, title_token

router = APIRouter(tags=["applications"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def application_pdf_filename(title: str | None, received_on: date | None) -> str:
    """Build the download name `Antrag_<Titel>_<YYYY-MM-DD>.pdf` (spec 000883).

    The title uses the cleanup of the protocol file name. A missing title or date
    leaves its part out.
    """
    parts = (
        "Antrag",
        *([token] if (token := title_token(title)) else []),
        *([received_on.isoformat()] if received_on is not None else []),
    )
    return "_".join(parts) + ".pdf"


def get_pdf_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> ApplicationPdfService:
    """Wire the service: storage from the app state, typst from the settings."""
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return ApplicationPdfService(
        session, storage=storage, typst=build_typst_client(settings), settings=settings
    )


@router.get(
    "/applications/{application_id}/pdf",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The Antrag as PDF."},
        **dict.fromkeys((400, 401, 403, 404, 503), _PROBLEM),
    },
)
async def get_application_pdf(
    session: DbSession,
    service: Annotated[ApplicationPdfService, Depends(get_pdf_service)],
    access: Annotated[Access, Depends(require_app_view)],
) -> Response:
    """Download the current version of an Antrag as PDF.

    The PDF holds the head data, the answers by section, the Kostenaufstellung, the
    names of the attached files and the valid decision. A field that the reader may
    not read prints as `(nicht sichtbar)`.
    """
    doc = await service.reader_doc(ApplicationsService(session), access)
    pdf = await service.render(doc)
    name = application_pdf_filename(doc.title, doc.received_on)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition("attachment", name)},
    )
