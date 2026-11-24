"""Shared dependencies of the admin routes: service factories, permission gates, error maps."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from app.deps import DbSession, Principal, SettingsDep, require_any_permission, require_principal
from app.modules.admin.oidc_mappings import OidcMappingService
from app.modules.admin.principal_merge import PrincipalMergeService
from app.modules.admin.principal_revoke import PrincipalRevokeService
from app.modules.admin.service import CdVariantService, ConfigService
from app.modules.admin.service.pdf_branding import PdfBrandingService
from app.modules.admin.site_config_service import SiteConfigService
from app.modules.delegations.mails import DelegationMailer, get_delegation_mailer
from app.modules.gremien.gremium_roles import GremiumRoleService
from app.shared.antiabuse import body_cap
from app.shared.errors import ProblemDetail

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return dict.fromkeys(codes, _PROBLEM)


def get_config_service(session: DbSession, request: Request) -> ConfigService:
    """Build the config service.

    The storage removes the file objects of the to-do comments of a deleted gremium.
    Without MinIO only the rows go.
    """
    return ConfigService(session, storage=getattr(request.app.state, "object_storage", None))


def get_site_config_service(session: DbSession, settings: SettingsDep) -> SiteConfigService:
    """Build the site-config service."""
    return SiteConfigService(session, settings=settings)


def get_gremium_role_service(session: DbSession) -> GremiumRoleService:
    """Build the gremium-role service."""
    return GremiumRoleService(session)


def get_oidc_mapping_service(session: DbSession) -> OidcMappingService:
    """Build the OIDC-mapping service."""
    return OidcMappingService(session)


def get_principal_merge_service(session: DbSession) -> PrincipalMergeService:
    """Build the account-merge service."""
    return PrincipalMergeService(session)


def get_principal_revoke_service(
    session: DbSession, settings: SettingsDep
) -> PrincipalRevokeService:
    """Build the rights-revoke service."""
    return PrincipalRevokeService(session, settings)


def get_cd_variant_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> CdVariantService:
    """Build the CD-variant service.

    Only the logo upload and download touch the object storage. Without MinIO
    (development, contract CI) those two routes answer 503.
    """
    storage = getattr(request.app.state, "object_storage", None)
    return CdVariantService(session, storage=storage, settings=settings)


def get_pdf_branding_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> PdfBrandingService:
    """Build the PDF branding service. Without MinIO the upload and the file answer 503."""
    storage = getattr(request.app.state, "object_storage", None)
    return PdfBrandingService(session, storage=storage, settings=settings)


ServiceDep = Annotated[ConfigService, Depends(get_config_service)]


PdfBrandingServiceDep = Annotated[PdfBrandingService, Depends(get_pdf_branding_service)]


SiteServiceDep = Annotated[SiteConfigService, Depends(get_site_config_service)]


GremiumRoleServiceDep = Annotated[GremiumRoleService, Depends(get_gremium_role_service)]


OidcMappingServiceDep = Annotated[OidcMappingService, Depends(get_oidc_mapping_service)]


CdVariantServiceDep = Annotated[CdVariantService, Depends(get_cd_variant_service)]


MergeServiceDep = Annotated[PrincipalMergeService, Depends(get_principal_merge_service)]


RevokeServiceDep = Annotated[PrincipalRevokeService, Depends(get_principal_revoke_service)]


DelegationMailerDep = Annotated[DelegationMailer, Depends(get_delegation_mailer)]


#: Content-Length cap for a logo upload, applied before FastAPI buffers the body.
#: Defense in depth next to the nginx cap and the authoritative in-service check.
_enforce_cd_logo_body = body_cap("attachment_max_bytes")


GremienAdmin = Annotated[Principal, Depends(require_principal("admin.gremien"))]


TypesAdmin = Annotated[Principal, Depends(require_principal("admin.types"))]


#: Deleting an application type is destructive, so it has its own permission.
TypesDeleteAdmin = Annotated[Principal, Depends(require_principal("admin.types_delete"))]


SiteAdmin = Annotated[Principal, Depends(require_principal("admin.site"))]


#: The feature switches change the platform for every person, so they have their own key.
FeaturesAdmin = Annotated[Principal, Depends(require_principal("admin.features"))]


RolesAdmin = Annotated[Principal, Depends(require_principal("admin.roles"))]


WebhookAdmin = Annotated[Principal, Depends(require_principal("webhook.manage"))]


UsersAdmin = Annotated[Principal, Depends(require_principal("admin.users"))]


#: A separate key, because the merge rewrites the history of two accounts and cannot
#: be undone.
MergeAdmin = Annotated[Principal, Depends(require_principal("admin.users.merge"))]


#: Revoke the rights of a person ("Rechte entziehen"). A separate key, because it
#: clears whole Gremien, the pool entries and the delegations of planned meetings. No
#: OAuth scope carries it, so it is a web-only action.
RevokeAdmin = Annotated[Principal, Depends(require_principal("admin.users.revoke_groups"))]


GroupMappingsAdmin = Annotated[Principal, Depends(require_principal("admin.group_mappings"))]


GremiumRolesAdmin = Annotated[Principal, Depends(require_principal("gremien.gremium_roles"))]


CdVariantsAdmin = Annotated[Principal, Depends(require_principal("admin.cd_variants"))]


#: The global flow save accepts EITHER key. ``create_global_flow`` gives the reason.
FlowVersionAdmin = Annotated[
    Principal, Depends(require_any_permission("admin.types", "flow.configure"))
]


#: All admin area permissions, for ANY-of reads and the admin landing page.
_ALL_ADMIN_AREAS = (
    "admin.site",
    "admin.gremien",
    "admin.types",
    "admin.roles",
    "admin.users",
    "admin.group_mappings",
    "gremien.gremium_roles",
    "admin.cd_variants",
    "admin.delegations",
    "admin.deadlines",
)


_GREMIEN = Depends(require_principal("admin.gremien"))


_TYPES = Depends(require_principal("admin.types"))


_SITE = Depends(require_principal("admin.site"))


_ROLES = Depends(require_principal("admin.roles"))


_USERS = Depends(require_principal("admin.users"))


_GROUP_MAPPINGS = Depends(require_principal("admin.group_mappings"))


_WEBHOOK = Depends(require_principal("webhook.manage"))


_CD_VARIANTS = Depends(require_principal("admin.cd_variants"))


#: The gremien page needs the CD-variant list as a dropdown source.
_CD_VARIANT_OPTIONS = Depends(require_any_permission("admin.gremien", "admin.cd_variants"))


_ANY_ADMIN_AREA = Depends(require_any_permission(*_ALL_ADMIN_AREAS))


#: The gremium-members page reads the gremium roles for the role labels. The group
#: mappings page reads them for its role dropdown.
_GREMIEN_OR_GREMIUM_ROLES = Depends(
    require_any_permission("admin.gremien", "gremien.gremium_roles", "admin.group_mappings")
)


#: The principal search serves the user page, the gremium members, the person picker
#: of the substitute pool and the person picker of the account erasure.
_PRINCIPAL_READERS = Depends(
    require_any_permission("admin.gremien", "admin.users", "admin.delegations", "privacy.manage")
)


#: The members page and the "represents" choice of the substitute pool read members.
_MEMBERSHIP_READERS = Depends(require_any_permission("admin.gremien", "admin.delegations"))


#: The flow editor and the budget tree read the global flow. Writes stay on the
#: strict permission.
_FLOW_READABLE = Depends(
    require_any_permission("admin.types", "flow.configure", "budget.structure")
)


#: The roles page, the users page and several config editors read the role list.
_ROLES_READ = Depends(
    require_any_permission(
        "admin.site",
        "admin.gremien",
        "admin.types",
        "admin.roles",
        "admin.users",
        "flow.configure",
    )
)


_WEBHOOK_OR_FLOW = Depends(require_any_permission("webhook.manage", "flow.configure"))


_TYPES_OR_FORM = Depends(require_any_permission("admin.types", "form.configure"))
