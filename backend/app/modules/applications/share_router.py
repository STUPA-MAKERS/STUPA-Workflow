"""The public half of a share link: ``GET /s/{token}``.

Mounted OUTSIDE ``/api`` on purpose. This answers with real HTML because Matrix, WhatsApp
and Signal build their previews by fetching the URL server-side and reading OpenGraph tags
out of the response; a bot that receives the Angular shell sees an empty page. nginx
proxies `/s/<token>` here before the SPA fallback can swallow it.

Unauthenticated by design, and therefore deliberately narrow:

* It does NOT go through ``resolve_access``. That answers "may this principal read this?",
  and here there is no principal. Reusing it would mean inventing one, which is how a
  public route ends up with more access than intended.
* A missing, revoked or expired token all answer the same 404. "This link expired" would
  tell a stranger they found a real one and were only too late.
* The response is built from `PublicApplication`, a fixed shape. A column added to
  `Application` later cannot appear here by accident, because nothing copies it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response
from sqlalchemy import select

from app.deps import DbSession, SettingsDep
from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _field_from_row
from app.modules.applications.share import ShareService, build_public_view
from app.modules.applications.share_page import render_share_page
from app.modules.forms.models import FormField
from app.shared.errors import NotFoundError
from app.shared.i18n import resolve_i18n

router = APIRouter(tags=["share"], include_in_schema=False)

#: A token is `secrets.token_urlsafe`, so the alphabet is fixed. Rejecting anything else
#: before a database round trip keeps a scanner from turning this into a query generator.
_TOKEN = r"^[A-Za-z0-9_-]{16,128}$"


@router.get("/s/{token}", response_class=Response)
async def public_application(
    session: DbSession,
    settings: SettingsDep,
    token: Annotated[str, Path(pattern=_TOKEN)],
) -> Response:
    """Render one shared application as a standalone HTML page."""
    service = ShareService(session, pepper=settings.magic_link_secret)
    share = await service.resolve(token)

    app = await session.get(Application, share.application_id)
    if app is None:
        # The row cascades with the application, so this is a race rather than a state.
        # Same 404 as an unknown token: still no signal about what existed.
        raise NotFoundError("no such link")

    app_type = await session.get(ApplicationType, app.type_id)
    gremium = (
        await session.get(Gremium, app.gremium_id) if app.gremium_id is not None else None
    )
    lang = app.lang or (gremium.default_lang if gremium is not None else "de")

    # The SAME field definitions the PDF renders from, through the same row mapper. Two
    # readers of one definition cannot disagree about which fields are personal.
    rows = (
        await session.scalars(
            select(FormField)
            .where(FormField.form_version_id == app.form_version_id)
            .order_by(FormField.order)
        )
    ).all()
    fields = [_field_from_row(r) for r in rows]

    view = build_public_view(
        app,
        fields=fields,
        type_name=(
            resolve_i18n(app_type.name_i18n, lang, "de") if app_type is not None else None
        ),
        gremium_name=gremium.name if gremium is not None else None,
        # The state label stays off the page: it is the committee's decision, and the
        # user asked for a view of the application rather than of its progress.
        state_label=None,
        lang=lang,
    )

    html = render_share_page(
        view,
        app_name=settings.app_name,
        canonical_url=f"{settings.public_base_url.rstrip('/')}/s/{token}",
        lang=lang,
    )
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            # Not for a search index: this page is for whoever holds the URL, not for
            # everyone who searches the applicant's name.
            "X-Robots-Tag": "noindex, nofollow",
            "X-Content-Type-Options": "nosniff",
            # No shared cache. A proxy holding this page would serve it to someone who
            # never had the link.
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
        },
    )

