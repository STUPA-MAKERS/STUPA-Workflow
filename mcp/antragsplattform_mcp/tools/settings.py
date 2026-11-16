"""Admin settings pages: switches, mail templates, defaults, periods, privacy and more.

A settings document is read with its `get_*` tool and written back whole with its
`set_*` tool: change only the keys you mean and keep the rest as read. Each page has
its own admin permission, and the server checks it.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from ._common import ToolGroup, api, params
from .meetings import _local_file, download_to

group = ToolGroup()

_LOGO_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".pdf"}
_LOGO_MAX = 10 * 1024 * 1024
_LOGO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
}


def _logo_part(file_path: str) -> tuple[str, bytes, str]:
    name, data, _ = _local_file(file_path, _LOGO_MAX, _LOGO_TYPES)
    suffix = name[name.rfind(".") :].lower()
    return name, data, _LOGO_MIME[suffix]


@group.tool
async def get_feature_switches() -> dict:
    """Read the feature switches (Funktionen) of the platform."""
    return await api().get("/admin/features")


@group.tool
async def set_feature_switches(switches: dict[str, Any]) -> dict:
    """Save the feature switches as a new active site-config version.

    Pass the object of `get_feature_switches` with the changed switches. A switch that
    goes off while the flow or an Antragsart uses the feature gives 409
    `feature_in_use` with `errors`; an unknown key gives 422.
    """
    return await api().put("/admin/features", json=switches)


@group.tool
async def get_gremium_defaults() -> dict:
    """Read the values that the form of a new Gremium starts with."""
    return await api().get("/admin/gremium-defaults")


@group.tool
async def set_gremium_defaults(defaults: dict[str, Any]) -> dict:
    """Replace the start values of a new Gremium; existing Gremien stay as they are."""
    return await api().put("/admin/gremium-defaults", json=defaults)


@group.tool
async def get_meeting_periods() -> dict:
    """Read the periods of the Geschäftsordnung (invitation, late excuse, absences, ...)."""
    return await api().get("/admin/meeting-periods")


@group.tool
async def set_meeting_periods(periods: dict[str, Any]) -> dict:
    """Replace the periods of the Geschäftsordnung; they apply at once."""
    return await api().put("/admin/meeting-periods", json=periods)


@group.tool
async def get_login_settings() -> dict:
    """Read the lifetime of a login in a browser tab and in the installed app.

    Only a person in the browser may change it; no tool writes it.
    """
    return await api().get("/admin/login-settings")


@group.tool
async def get_help_ticket_settings() -> dict:
    """Read the settings of "Hilfe & Tickets": wiki link, public reports, mails, retention."""
    return await api().get("/admin/help-tickets")


@group.tool
async def set_help_ticket_settings(settings: dict[str, Any]) -> dict:
    """Save the settings of "Hilfe & Tickets" as a new active site-config version.

    A `wikiUrl` that is not http(s) or a `retentionMonths` out of 1 to 120 gives 422.
    """
    return await api().put("/admin/help-tickets", json=settings)


@group.tool
async def list_mail_templates() -> list:
    """List all mail templates: built-in and overrides, with subject, body and placeholders."""
    return await api().get("/admin/mail-templates")


@group.tool
async def save_mail_template(
    key: str,
    subject_i18n: dict[str, str],
    body_i18n: dict[str, str],
    body_html_i18n: dict[str, str] | None = None,
) -> dict:
    """Create or update the override of a mail template by its key, also a built-in key.

    The texts are Jinja2 (sandboxed) by language; use the `placeholders` of the template.
    """
    return await api().put(
        "/admin/mail-templates",
        json=params(
            key=key, subjectI18n=subject_i18n, bodyI18n=body_i18n, bodyHtmlI18n=body_html_i18n
        ),
    )


@group.tool
async def create_mail_template(
    key: str,
    subject_i18n: dict[str, str],
    body_i18n: dict[str, str],
    body_html_i18n: dict[str, str] | None = None,
    placeholders: dict[str, str] | None = None,
) -> dict:
    """Create a new mail template with its own key."""
    return await api().post(
        "/admin/mail-templates",
        json=params(
            key=key, subjectI18n=subject_i18n, bodyI18n=body_i18n,
            bodyHtmlI18n=body_html_i18n, placeholders=placeholders,
        ),
    )


@group.tool
async def update_mail_template(
    template_id: str,
    subject_i18n: dict[str, str] | None = None,
    body_i18n: dict[str, str] | None = None,
    body_html_i18n: dict[str, str] | None = None,
    placeholders: dict[str, str] | None = None,
) -> dict:
    """Patch a stored mail template by its id."""
    return await api().patch(
        f"/admin/mail-templates/{template_id}",
        json=params(
            subjectI18n=subject_i18n, bodyI18n=body_i18n, bodyHtmlI18n=body_html_i18n,
            placeholders=placeholders,
        ),
    )


@group.tool
async def reset_mail_template(key: str) -> dict:
    """Delete the override of a mail template and restore the built-in text."""
    return await api().delete(f"/admin/mail-templates/by-key/{key}")


@group.tool
async def preview_mail_template(
    template_id: str | None = None,
    subject_i18n: dict[str, str] | None = None,
    body_i18n: dict[str, str] | None = None,
    body_html_i18n: dict[str, str] | None = None,
    lang: str = "de",
    context: dict[str, Any] | None = None,
) -> dict:
    """Render a mail template with sample values: a stored one by id, or a draft text.

    Without `template_id` pass `subject_i18n` and `body_i18n`.
    """
    if template_id is not None:
        return await api().post(
            f"/admin/mail-templates/{template_id}/preview",
            json={"lang": lang, "context": context or {}},
        )
    return await api().post(
        "/admin/mail-templates/preview",
        json=params(
            subjectI18n=subject_i18n or {}, bodyI18n=body_i18n or {},
            bodyHtmlI18n=body_html_i18n, lang=lang, context=context or {},
        ),
    )


@group.tool
async def list_config_revisions(entity_type: str, entity_id: str) -> list:
    """List the saved versions of a configuration, newest first (version sidebar).

    Args:
        entity_type: `form`, `flow` or `site_config`.
        entity_id: The id of the configured object.
    """
    return await api().get(
        "/admin/config-revisions", params={"entityType": entity_type, "entityId": entity_id}
    )


@group.tool
async def get_config_revision_diff(revision_id: str) -> dict:
    """Return the field diff of a saved version against the version before it."""
    return await api().get(f"/admin/config-revisions/{revision_id}/diff")


@group.tool
async def restore_config_revision(revision_id: str) -> dict:
    """Make an earlier version of a configuration the active one again.

    The earlier versions stay. Ask the user before you call this.
    """
    await api().post(f"/admin/config-revisions/{revision_id}/restore")
    return {"restored": True}


@group.tool
async def list_audit_actors() -> list:
    """List the actors of the audit log with their names, for the actor filter."""
    return await api().get("/admin/audit/actors")


@group.tool
async def run_audit_verification() -> dict:
    """Verify the whole audit chain now and store the result (audit.verify).

    Another running check gives 409; a manual check runs again only after 5 minutes.
    """
    return await api().post("/admin/audit/verify")


@group.tool
async def revert_audit_entry(entry_id: int) -> dict:
    """Revert the change that an audit entry describes (audit.revert).

    404 for a missing entry, 409 when it is not revertable or stale. The revert writes
    its own entry, which can be reverted too. Ask the user before you call this.
    """
    return await api().post(f"/admin/audit/{entry_id}/revert")


@group.tool
async def webhook_delivery_status() -> list:
    """Return the newest delivery state per webhook: sent, pending, dead or never."""
    return await api().get("/admin/webhooks/delivery-status")


@group.tool
async def list_agent_grants(principal_id: str | None = None) -> dict:
    """List the live agent tokens of every person, newest first (admin.users)."""
    return await api().get("/admin/oauth-grants", params=params(principalId=principal_id))


@group.tool
async def revoke_agent_grant(grant_id: str) -> dict:
    """Revoke the agent token of any person, for example after a leak (admin.users).

    Ask the user before you call this.
    """
    await api().delete(f"/admin/oauth-grants/{grant_id}")
    return {"revoked": True}


@group.tool
async def get_pdf_asset(slot: Literal["logo", "footer"]) -> dict | None:
    """Read a graphic of the PDF branding: the export logo or the footer graphic."""
    return await api().get(f"/admin/pdf-assets/{slot}")


@group.tool
async def upload_pdf_asset(slot: Literal["logo", "footer"], file_path: str) -> dict:
    """Upload a local PNG, JPEG, WebP, SVG or PDF as a graphic of the PDF branding."""
    name, data, mime = _logo_part(file_path)
    return await api().put(f"/admin/pdf-assets/{slot}", files={"file": (name, data, mime)})


@group.tool
async def reset_pdf_asset(slot: Literal["logo", "footer"]) -> dict:
    """Set the built-in graphic of the slot again: the STUPA logo or the Skyline."""
    return await api().post(f"/admin/pdf-assets/{slot}/default")


@group.tool
async def clear_pdf_asset(slot: Literal["logo", "footer"]) -> dict:
    """Empty the slot; the PDFs then carry no graphic there."""
    await api().delete(f"/admin/pdf-assets/{slot}")
    return {"cleared": True}


@group.tool
async def download_pdf_asset(
    slot: Literal["logo", "footer"], target_path: str, overwrite: bool = False
) -> dict:
    """Download the upload of a PDF branding slot to a local file."""
    return await download_to(
        "GET",
        f"/admin/pdf-assets/{slot}/file",
        target_path,
        overwrite=overwrite,
        fallback=f"pdf-{slot}",
    )


@group.tool
async def upload_cd_variant_logo(
    variant_id: str, slot: Literal["title", "footer", "square"], file_path: str
) -> dict:
    """Upload a local logo into a slot of a CD variant (admin.cd_variants).

    `title` and `footer` take PNG, JPEG, WebP, SVG and PDF. `square` takes PNG, JPEG or
    WebP only, square and at least 256 x 256 px, and replaces the square logo.
    """
    name, data, mime = _logo_part(file_path)
    return await api().post(
        f"/admin/cd-variants/{variant_id}/logos",
        files={"file": (name, data, mime)},
        data={"slot": slot},
    )


@group.tool
async def order_cd_variant_logos(
    variant_id: str, slot: Literal["title", "footer", "square"], logo_ids: list[str]
) -> list:
    """Set the order of the logos inside one slot; the list names every logo of the slot."""
    return await api().put(
        f"/admin/cd-variants/{variant_id}/logos/order", json={"slot": slot, "logoIds": logo_ids}
    )


@group.tool
async def download_cd_variant_logo(
    logo_id: str, target_path: str, square: bool = False, overwrite: bool = False
) -> dict:
    """Download a logo of a CD variant to a local file; `square` reads the square logo."""
    path = f"/admin/cd-variant-logos/{logo_id}/file"
    if square:
        path = f"/admin/cd-variant-logos/{logo_id}/square"
    return await download_to(
        "GET", path, target_path, overwrite=overwrite, fallback=f"logo-{logo_id}"
    )


@group.tool
async def get_privacy_settings() -> dict:
    """Read the privacy settings: the global retention default in months."""
    return await api().get("/admin/privacy/settings")


@group.tool
async def set_privacy_settings(default_retention_months: int) -> dict:
    """Change the global retention default in months (at least 1)."""
    return await api().put(
        "/admin/privacy/settings", json={"defaultRetentionMonths": default_retention_months}
    )


@group.tool
async def list_erasure_requests(status: str | None = None) -> list:
    """List the privacy erasure requests (Art. 17), optionally by status.

    No tool runs an erasure: a person does that in the app, because it cannot be undone.
    """
    return await api().get("/admin/privacy/erasures", params=params(status=status))


@group.tool
async def reject_erasure_request(request_id: str, reason: str | None = None) -> dict:
    """Reject an erasure request; the reason goes out by mail."""
    return await api().post(
        f"/admin/privacy/erasures/{request_id}/reject", json=params(reason=reason)
    )


@group.tool
async def export_personal_data(email: str, target_path: str, overwrite: bool = False) -> dict:
    """Export all personal data stored for an e-mail address as XLSX (Art. 15 GDPR).

    The audit log records the export. The file goes to a local path, never into the chat.
    """
    return await download_to(
        "GET",
        "/admin/privacy/export",
        target_path,
        overwrite=overwrite,
        fallback="auskunft.xlsx",
        query={"email": email},
    )


def register(mcp: FastMCP) -> None:
    """Register the admin settings tool group."""
    group.register(mcp)
