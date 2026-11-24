"""Admin/config API router.

Endpoints for versioned config CRUD (gremien, application types, the global
flow), RBAC (roles/group-mappings, read-only role assignments), webhooks, corporate-design
variants, config-schemas and site-config/branding, plus a public auth-free
branding read.

RBAC is server-side authoritative. ``require_principal`` answers 401 or 403.
The frontend is only a UX gate. Per-area permissions: ``admin.gremien``,
``admin.types``, ``admin.site``, ``admin.roles``, ``admin.cd_variants``,
``admin.deadlines`` (guest settings, meeting settings), ``webhook.manage``.

``notification-rules`` and ``mail-templates`` live in the notifications module.
``/admin/audit`` lives in audit and the form versions live in forms. This
module does not duplicate them.

Exactly one global flow applies to all application types. A site-config, branding or
"Hilfe & Tickets" save writes a new active version directly, without a draft. The
gremium mappings (OIDC group to gremium membership, OIDC group to gremium role) are
separate from the global group mappings and from each other.

Layout of the package: one module per area (``gremien_router``, ``cd_variants_router``,
``types_router``, ``principals_router``, ``rbac_router``, ``webhooks_router``,
``settings_router``, ``site_router``, ``branding_router``), each with its own routers,
and ``deps`` with the service factories and the permission gates. This package combines
them into ``router`` (prefix ``/admin``), ``authed_router`` (master-data reads for any
authenticated principal, without the ``/admin`` prefix) and ``public_router`` (auth-free
branding), in the order of the routes before the split, so the match order stays the
same. The area modules end in ``_router``, so they count as router files (the commits of
a route stay in the route). The package re-exports the service factories, so
``from app.modules.admin.router import get_config_service`` keeps working.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.admin.router import (
    branding_router,
    cd_variants_router,
    gremien_router,
    principals_router,
    rbac_router,
    settings_router,
    site_router,
    types_router,
    webhooks_router,
)
from app.modules.admin.router.deps import (
    get_cd_variant_service,
    get_config_service,
    get_gremium_role_service,
    get_oidc_mapping_service,
    get_pdf_branding_service,
    get_principal_merge_service,
    get_principal_revoke_service,
    get_site_config_service,
)
from app.modules.admin.router.settings_router import (
    get_guest_settings_service,
    get_login_settings_service,
    get_meeting_settings_service,
)

router = APIRouter()
for _area in (
    gremien_router,
    cd_variants_router,
    types_router,
    principals_router,
    rbac_router,
    webhooks_router,
    settings_router,
    site_router,
):
    router.include_router(_area.router)

authed_router = APIRouter()
authed_router.include_router(gremien_router.authed_router)
authed_router.include_router(cd_variants_router.authed_router)

public_router = APIRouter()
public_router.include_router(branding_router.public_router)

__all__ = [
    "authed_router",
    "get_cd_variant_service",
    "get_config_service",
    "get_gremium_role_service",
    "get_guest_settings_service",
    "get_login_settings_service",
    "get_meeting_settings_service",
    "get_oidc_mapping_service",
    "get_pdf_branding_service",
    "get_principal_merge_service",
    "get_principal_revoke_service",
    "get_site_config_service",
    "public_router",
    "router",
]
