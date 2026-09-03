"""The public half of a share link: ``GET /s/{token}``.

Mounted OUTSIDE ``/api`` on purpose. This answers with real HTML because Matrix, WhatsApp
and Signal build their previews by fetching the URL server-side and reading OpenGraph tags
out of the response; a bot that receives the Angular shell sees an empty page. nginx
proxies `/s/<token>` here before the SPA fallback can swallow it.

Readable WITHOUT a login, and therefore deliberately narrow:

* The token alone decides what may be seen. A session, where there is one, only decides
  whether the reader is sent to the real record instead — it never widens what this route
  will show. A reader with no account, or one whose account may not read applications,
  gets exactly the same reduced page as before.
* It does NOT go through ``resolve_access``. That answers "may this principal read this?"
  and raises when the answer is no; this route asks the far smaller question of whether
  the reader would be better served by the record itself, and falls back to the page when
  the answer is no. Granting access through it would be how a public route ends up with
  more reach than intended.
* A missing, revoked or expired token all answer the same 404, and that is settled BEFORE
  anyone is redirected. Otherwise a signed-in reader could tell a revoked link from an
  invented one by whether it bounced.
* The response is built from `PublicApplication`, a fixed shape. A column added to
  `Application` later cannot appear here by accident, because nothing copies it.
* One URL, two answers, so every response carries ``Vary: Cookie`` and stays out of shared
  caches.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.deps import DbSession, SettingsDep, get_current_principal
from app.modules.admin.models import ApplicationType, Gremium
from app.modules.admin.site_config_service import DEFAULT_APP_NAME, SiteConfigService
from app.modules.applications.access import READ_ALL_PERMISSION
from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _field_from_row
from app.modules.applications.share import ShareService, build_public_view
from app.modules.applications.share_page import render_share_page, share_csp
from app.modules.auth.principal import Principal
from app.modules.forms.models import FormField
from app.shared.errors import NotFoundError
from app.shared.i18n import resolve_i18n

router = APIRouter(tags=["share"], include_in_schema=False)

#: A token is `secrets.token_urlsafe`, so the alphabet is fixed. Rejecting anything else
#: before a database round trip keeps a scanner from turning this into a query generator.
_TOKEN = r"^[A-Za-z0-9_-]{16,128}$"

#: Headers every answer from this route carries, whichever answer it is.
#:
#: `Vary: Cookie` because one URL now has TWO answers: the reduced page for whoever holds
#: the link, and a redirect for a member who can open the record itself. A cache that
#: ignored the cookie could hand one reader the other's answer.
_COMMON_HEADERS = {
    # Not for a search index: this page is for whoever holds the URL, not for everyone
    # who searches the applicant's name.
    "X-Robots-Tag": "noindex, nofollow",
    # No shared cache. A proxy holding this would serve it to someone who never had the
    # link.
    "Cache-Control": "private, no-store",
    "Vary": "Cookie",
    "Referrer-Policy": "no-referrer",
}


@router.get("/s/{token}", response_class=Response)
async def public_application(
    session: DbSession,
    settings: SettingsDep,
    token: Annotated[str, Path(pattern=_TOKEN)],
    principal: Annotated[Principal | None, Depends(get_current_principal)] = None,
) -> Response:
    """Render one shared application as a standalone HTML page."""
    service = ShareService(session, pepper=settings.magic_link_secret)
    share = await service.resolve(token)

    app = await session.get(Application, share.application_id)
    if app is None:
        # The row cascades with the application, so this is a race rather than a state.
        # Same 404 as an unknown token: still no signal about what existed.
        raise NotFoundError("no such link")

    # A member who can open the record itself is sent to it. The reduced view exists for
    # readers with no account; showing a signed-in member a copy with less on it, next to
    # a button that opens the real thing, is a step they should not have to take.
    #
    # AFTER the token is resolved, never before: otherwise a signed-in reader could tell
    # a revoked link from an invented one by whether it bounced.
    #
    # Only for a principal who may actually read an application. Redirecting anyone else
    # would trade a page they can read for a 403. A preview bot carries no session at
    # all, so it takes the anonymous path and the OpenGraph tags survive, which is the
    # whole reason this route answers with HTML.
    if principal is not None and (
        principal.has("application.read") or principal.has(READ_ALL_PERMISSION)
    ):
        base = settings.public_base_url.rstrip("/")
        return RedirectResponse(
            url=f"{base}/applications/{app.id}",
            # 303: "the answer to your GET is over there", and never cached by default.
            status_code=303,
            headers=_COMMON_HEADERS,
        )

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

    # The BRANDING name, not `settings.app_name` — that is the FastAPI title and reads
    # "Antragsplattform API". This name goes into the og:title, which is the one piece of
    # the page that lands permanently on a chat server.
    branding = (await SiteConfigService(session).public()).branding
    app_name = branding.app_name.strip() or DEFAULT_APP_NAME
    # The wordmark is the branding a deployment really configures. `imagemark` is the
    # fallback, because a square mark still names the instance; `favicon` is too small to
    # read as a header logo, so a deployment that set only that one gets the name alone.
    logo = branding.logos.get("wordmark") or branding.logos.get("imagemark")

    base = settings.public_base_url.rstrip("/")
    html = render_share_page(
        view,
        app_name=app_name,
        canonical_url=f"{base}/s/{token}",
        lang=lang,
        # The record itself, not the list it lives on. A reader with an account lands on
        # the application; one without meets the login, which is the honest answer.
        app_url=f"{base}/applications/{app.id}",
        logo_url=logo.url if logo is not None else None,
    )
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            **_COMMON_HEADERS,
            # Its own policy. `SecurityHeadersMiddleware` only fills a CSP in where none
            # is set, and the API-wide `default-src 'none'` would block this page's own
            # stylesheet and serve it as raw unstyled markup. The logo widens `img-src`
            # by exactly its own source, so the policy has to be built per response.
            "Content-Security-Policy": share_csp(logo.url if logo is not None else None),
            "X-Content-Type-Options": "nosniff",
        },
    )

