"""Admin tools.

This group covers Gremien, RBAC, application types, webhooks,
guest and meeting settings, notifications, site config, UI texts and languages, and
the audit log.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def list_gremien() -> dict:
    """List all Gremien."""
    return await api().get("/admin/committees")


@group.tool
async def create_gremium(gremium: S.GremiumCreate) -> dict:
    """Create a Gremium. Requires admin.gremien."""
    return await api().post("/admin/committees", json=dump_create(gremium))


@group.tool
async def update_gremium(gremium_id: str, patch: S.GremiumUpdate) -> dict:
    """Patch a Gremium. Requires admin.gremien."""
    return await api().patch(f"/admin/committees/{gremium_id}", json=dump_patch(patch))


@group.tool
async def delete_gremium(gremium_id: str) -> dict:
    """Delete a Gremium. Requires admin.gremien.

    409 `gremium_decides_vote` while the Gremium decides the running vote of an
    application (`voteGremiumId`).
    """
    return await api().delete(f"/admin/committees/{gremium_id}")


@group.tool
async def list_cd_variants() -> dict:
    """List the corporate-design variants. Requires admin.cd_variants or admin.gremien.

    Use the returned id as `cdVariantId` when you create or patch a Gremium. Each
    logo has a `slot`: `title` and `footer` go into the PDF, `square` is the 1:1
    logo that the app shows for a Gremium (at most one per variant).
    """
    return await api().get("/admin/cd-variants")


@group.tool
async def create_cd_variant(variant: S.CdVariantCreate) -> dict:
    """Create a corporate-design variant. Requires admin.cd_variants."""
    return await api().post("/admin/cd-variants", json=dump_create(variant))


@group.tool
async def update_cd_variant(variant_id: str, patch: S.CdVariantUpdate) -> dict:
    """Patch a corporate-design variant. Requires admin.cd_variants."""
    return await api().patch(f"/admin/cd-variants/{variant_id}", json=dump_patch(patch))


@group.tool
async def delete_cd_variant(variant_id: str) -> dict:
    """Delete a corporate-design variant. Requires admin.cd_variants.

    The call gives 409 while a Gremium still uses the variant.
    """
    return await api().delete(f"/admin/cd-variants/{variant_id}")


@group.tool
async def add_cd_variant_vendored_logo(
    variant_id: str, logo: S.CdVariantLogoVendoredCreate
) -> dict:
    """Add a logo that the render service ships to a variant. Requires admin.cd_variants.

    Deprecated: the worker turns a vendored logo into a normal upload at its next
    start, and a later release removes vendored logos. The slot `square` gives 422.
    """
    return await api().post(
        f"/admin/cd-variants/{variant_id}/logos/vendored", json=dump_create(logo)
    )


@group.tool
async def delete_cd_variant_logo(logo_id: str) -> dict:
    """Remove one logo from a corporate-design variant. Requires admin.cd_variants."""
    return await api().delete(f"/admin/cd-variant-logos/{logo_id}")


@group.tool
async def get_gremium_mail_recipients(gremium_id: str) -> dict:
    """List the extra protocol recipients of a Gremium.

    A finalized protocol goes to the active members and also to these addresses.
    """
    return await api().get(f"/admin/committees/{gremium_id}/mail-recipients")


@group.tool
async def set_gremium_mail_recipients(gremium_id: str, recipients: list[str]) -> dict:
    """Replace the extra protocol recipients of a Gremium.

    The call is an idempotent PUT. An empty list sends the protocol to the members
    only. Requires admin.gremien.
    """
    return await api().put(
        f"/admin/committees/{gremium_id}/mail-recipients", json={"recipients": recipients}
    )


@group.tool
async def list_gremium_roles(gremium_id: str) -> dict:
    """List the roles that are scoped to a Gremium."""
    return await api().get(f"/admin/committees/{gremium_id}/roles")


@group.tool
async def create_gremium_role(gremium_id: str, role: S.GremiumRoleCreate) -> dict:
    """Create a role that is scoped to a Gremium. Requires admin.gremien."""
    return await api().post(f"/admin/committees/{gremium_id}/roles", json=dump_create(role))


@group.tool
async def update_gremium_role(role_id: str, patch: S.GremiumRoleUpdate) -> dict:
    """Patch a role that is scoped to a Gremium. Requires admin.gremien."""
    return await api().patch(f"/admin/committee-roles/{role_id}", json=dump_patch(patch))


@group.tool
async def delete_gremium_role(role_id: str) -> dict:
    """Delete a role that is scoped to a Gremium. Requires admin.gremien."""
    return await api().delete(f"/admin/committee-roles/{role_id}")


@group.tool
async def list_gremium_memberships(gremium_id: str) -> dict:
    """List the memberships of a Gremium.

    A membership links a member to a role of that Gremium. Each item has the keys
    id, principalId, gremiumId, gremiumRoleId, displayName, email and active. active is
    true when the principal is active and the membership is valid now; the member
    count of the Gremium counts only these rows. The list is read-only. The platform
    derives the memberships from the OIDC groups of the members, the membership
    mappings and the Gremium role mappings. To change a membership, change a mapping
    or the groups in the IdP.
    """
    return await api().get(f"/admin/committees/{gremium_id}/memberships")


@group.tool
async def list_gremium_membership_mappings() -> dict:
    """List the mappings from an OIDC group to the membership in a Gremium.

    Each item has the keys id, gremiumId and oidcGroup. A principal in a mapped group
    becomes a member of the Gremium with the default Gremium role `member`. Requires
    admin.group_mappings.
    """
    return await api().get("/admin/committee-membership-mappings")


@group.tool
async def create_gremium_membership_mapping(
    mapping: S.GremiumMembershipMappingCreate,
) -> dict:
    """Map an OIDC group to the membership in a Gremium. Requires admin.group_mappings.

    The platform then syncs the memberships of all principals. A pair of group and
    Gremium that exists already gives 409. An unknown Gremium gives 404. A group with
    the prefix `vote:` gives 422.
    """
    return await api().post("/admin/committee-membership-mappings", json=dump_create(mapping))


@group.tool
async def update_gremium_membership_mapping(
    mapping_id: str, patch: S.GremiumMembershipMappingUpdate
) -> dict:
    """Patch the group or the Gremium of a membership mapping.

    Requires admin.group_mappings. The platform then syncs the memberships of all
    principals.
    """
    return await api().patch(
        f"/admin/committee-membership-mappings/{mapping_id}", json=dump_patch(patch)
    )


@group.tool
async def delete_gremium_membership_mapping(mapping_id: str) -> dict:
    """Delete a membership mapping. Requires admin.group_mappings.

    The platform then removes the memberships that only this mapping gave.
    """
    return await api().delete(f"/admin/committee-membership-mappings/{mapping_id}")


@group.tool
async def list_gremium_role_mappings() -> dict:
    """List the mappings from an OIDC group to a role in a Gremium.

    Each item has the keys id, gremiumId, gremiumRoleId and oidcGroup. gremiumId is the
    Gremium of the role. A role mapping applies only to a principal who is a member of
    that Gremium through a membership mapping. Requires admin.group_mappings.
    """
    return await api().get("/admin/committee-role-mappings")


@group.tool
async def create_gremium_role_mapping(mapping: S.GremiumRoleMappingCreate) -> dict:
    """Map an OIDC group to a role in a Gremium. Requires admin.group_mappings.

    The role applies only to members of the Gremium. Map the membership with
    `create_gremium_membership_mapping`. The platform then syncs the memberships of
    all principals. A pair of group and role that exists already gives 409. An
    unknown role gives 404. A group with the prefix `vote:` gives 422.
    """
    return await api().post("/admin/committee-role-mappings", json=dump_create(mapping))


@group.tool
async def update_gremium_role_mapping(
    mapping_id: str, patch: S.GremiumRoleMappingUpdate
) -> dict:
    """Patch the group or the Gremium role of a role mapping.

    Requires admin.group_mappings. The platform then syncs the memberships of all
    principals.
    """
    return await api().patch(
        f"/admin/committee-role-mappings/{mapping_id}", json=dump_patch(patch)
    )


@group.tool
async def delete_gremium_role_mapping(mapping_id: str) -> dict:
    """Delete a Gremium role mapping. Requires admin.group_mappings.

    The platform then removes the Gremium roles that only this mapping gave.
    """
    return await api().delete(f"/admin/committee-role-mappings/{mapping_id}")


@group.tool
async def list_permissions() -> dict:
    """List the catalog of assignable permissions."""
    return await api().get("/admin/permissions")


@group.tool
async def list_roles() -> dict:
    """List the global roles and their permissions."""
    return await api().get("/admin/roles")


@group.tool
async def create_role(role: S.RoleCreate) -> dict:
    """Create a global role. Requires admin.roles."""
    return await api().post("/admin/roles", json=dump_create(role))


@group.tool
async def update_role(role_id: str, patch: S.RoleUpdate) -> dict:
    """Patch the label or the permissions of a global role. Requires admin.roles."""
    return await api().patch(f"/admin/roles/{role_id}", json=dump_patch(patch))


@group.tool
async def delete_role(role_id: str) -> dict:
    """Delete a global role. Requires admin.roles."""
    return await api().delete(f"/admin/roles/{role_id}")


@group.tool
async def list_role_assignments() -> dict:
    """List the RBAC role assignments (read-only).

    An assignment links a principal to a global role. Only the bootstrap writes
    assignments. The global roles come from the OIDC
    groups through the group mappings. See `list_group_mappings`.
    """
    return await api().get("/admin/role-assignments")


@group.tool
async def list_principals(
    q: str | None = None,
    last_login_before: str | None = None,
    include_never: bool | None = None,
    has_groups: bool | None = None,
) -> dict:
    """List the principals (users).

    Each item has `oidcGroups`, the OIDC groups as of the last login. These groups
    drive the group mappings. `hasAccess` tells whether the person still has a
    membership, a role, a pool entry, a delegation or an OIDC group. The revoke of
    these rights ("Rechte entziehen") is a web-only action and has no tool.

    Args:
        q: Filter by a substring of the sub or the email.
        last_login_before: ISO date (YYYY-MM-DD). Keep the people whose last login
            is before that day.
        include_never: True adds the people who never logged in. Without
            `last_login_before` it keeps only those.
        has_groups: True keeps the people with OIDC groups, False those without.
    """
    return await api().get(
        "/admin/principals",
        params=params(
            q=q,
            lastLoginBefore=last_login_before,
            includeNever=include_never,
            hasGroups=has_groups,
        ),
    )


@group.tool
async def update_principal(principal_id: str, active: bool) -> dict:
    """Activate or deactivate a principal. Requires admin.roles."""
    return await api().patch(
        f"/admin/principals/{principal_id}", json={"active": active}
    )


@group.tool
async def list_group_mappings() -> dict:
    """List the mappings from an OIDC group to a global role."""
    return await api().get("/admin/group-mappings")


@group.tool
async def create_group_mapping(mapping: S.GroupMappingCreate) -> dict:
    """Map an OIDC group to a global role. Requires admin.group_mappings.

    A global role has no Gremium scope. For a Gremium, use
    `create_gremium_membership_mapping` and `create_gremium_role_mapping`.
    """
    return await api().post("/admin/group-mappings", json=dump_create(mapping))


@group.tool
async def update_group_mapping(mapping_id: str, patch: S.GroupMappingUpdate) -> dict:
    """Patch the group or the global role of a group mapping. Requires admin.group_mappings."""
    return await api().patch(f"/admin/group-mappings/{mapping_id}", json=dump_patch(patch))


@group.tool
async def delete_group_mapping(mapping_id: str) -> dict:
    """Delete a mapping from an OIDC group to a global role. Requires admin.group_mappings."""
    return await api().delete(f"/admin/group-mappings/{mapping_id}")


@group.tool
async def list_application_types() -> dict:
    """List the application types in the admin view."""
    return await api().get("/admin/application-types")


@group.tool
async def create_application_type(type: S.ApplicationTypeCreate) -> dict:
    """Create an application type. Requires admin.types."""
    return await api().post("/admin/application-types", json=dump_create(type))


@group.tool
async def update_application_type(type_id: str, patch: S.ApplicationTypeUpdate) -> dict:
    """Patch an application type. Requires admin.types."""
    return await api().patch(
        f"/admin/application-types/{type_id}", json=dump_patch(patch)
    )


@group.tool
async def delete_application_type(type_id: str) -> dict:
    """Delete an application type. Requires admin.types_delete.

    409 while applications of this type exist. Ask the user before you call this.
    """
    await api().delete(f"/admin/application-types/{type_id}")
    return {"deleted": True}


@group.tool
async def move_application_type(type_id: str, by: Literal[-1, 1]) -> list:
    """Move an application type one place up (-1) or down (1) inside its group."""
    return await api().post(f"/admin/application-types/{type_id}/move", json={"by": by})


@group.tool
async def list_application_type_groups() -> list:
    """List the groups of Antragsarten in their order (admin view)."""
    return await api().get("/admin/application-type-groups")


@group.tool
async def create_application_type_group(group_in: S.ApplicationTypeGroupCreate) -> dict:
    """Create a group of Antragsarten at the end of the order. Requires admin.types.

    Put a type into the group with `update_application_type` and `groupId`.
    """
    return await api().post("/admin/application-type-groups", json=dump_create(group_in))


@group.tool
async def update_application_type_group(
    group_id: str, patch: S.ApplicationTypeGroupUpdate
) -> dict:
    """Change the name or the text of a group of Antragsarten. Requires admin.types."""
    return await api().patch(
        f"/admin/application-type-groups/{group_id}", json=dump_patch(patch)
    )


@group.tool
async def delete_application_type_group(group_id: str) -> dict:
    """Delete a group of Antragsarten; its types stay without a group. Requires admin.types."""
    await api().delete(f"/admin/application-type-groups/{group_id}")
    return {"deleted": True}


@group.tool
async def move_application_type_group(group_id: str, by: Literal[-1, 1]) -> list:
    """Move a group of Antragsarten one place up (-1) or down (1)."""
    return await api().post(
        f"/admin/application-type-groups/{group_id}/move", json={"by": by}
    )


@group.tool
async def list_submittable_application_types(lang: str | None = None) -> dict:
    """List the application types as the apply wizard shows them, with their group."""
    return await api().get("/application-types", params=params(lang=lang, limit=100))


@group.tool
async def list_apply_type_groups(lang: str | None = None) -> list:
    """List the groups of Antragsarten of step 1 of the apply wizard, with their types."""
    return await api().get("/application-type-groups", params=params(lang=lang))


@group.tool
async def list_webhooks() -> dict:
    """List the configured webhooks."""
    return await api().get("/admin/webhooks")


@group.tool
async def create_webhook(webhook: S.WebhookCreate) -> dict:
    """Create a webhook. Requires webhook.manage."""
    return await api().post("/admin/webhooks", json=dump_create(webhook))


@group.tool
async def update_webhook(webhook_id: str, patch: S.WebhookUpdate) -> dict:
    """Patch a webhook. Requires webhook.manage."""
    return await api().patch(f"/admin/webhooks/{webhook_id}", json=dump_patch(patch))


@group.tool
async def delete_webhook(webhook_id: str) -> dict:
    """Delete a webhook and its delivery history. Requires webhook.manage."""
    return await api().delete(f"/admin/webhooks/{webhook_id}")


@group.tool
async def get_notification_settings() -> dict:
    """Get the platform notification settings, such as the task reminder cadence. Admin."""
    return await api().get("/admin/notification-settings")


@group.tool
async def update_notification_settings(patch: S.NotificationSettingsUpdate) -> dict:
    """Patch the platform notification settings.

    The fields are `taskReminderEnabled`, `taskReminderAfterDays` and
    `taskReminderRepeatDays`. Admin.
    """
    return await api().put("/admin/notification-settings", json=dump_patch(patch))


@group.tool
async def get_guest_settings() -> dict:
    """Get the settings for applications without an account.

    `confirmTtlHours` is the time a guest has to confirm the email before the platform
    discards the application. `linkTtlDays` is the lifetime of a new magic link
    (null = no expiry). Requires admin.deadlines.
    """
    return await api().get("/admin/guest-settings")


@group.tool
async def update_guest_settings(settings: S.GuestSettingsUpdate) -> dict:
    """Replace the settings for applications without an account.

    Send both fields. `linkTtlDays` is required: `null` gives magic links without an
    expiry. To keep the current lifetime, read it with `get_guest_settings` first. A new
    `confirmTtlHours` applies to the waiting applications too. Requires admin.deadlines.
    """
    return await api().put(
        "/admin/guest-settings",
        json={
            "confirmTtlHours": settings.confirmTtlHours,
            "linkTtlDays": settings.linkTtlDays,
        },
    )


@group.tool
async def get_meeting_settings() -> dict:
    """Get the open window of meetings.

    `openLeadMinutes` is the earliest open of a meeting before its planned start.
    Requires admin.deadlines.
    """
    return await api().get("/admin/meeting-settings")


@group.tool
async def update_meeting_settings(settings: S.MeetingSettingsUpdate) -> dict:
    """Replace the open window of meetings.

    The change applies to every planned meeting at once. Requires admin.deadlines.
    """
    return await api().put(
        "/admin/meeting-settings", json={"openLeadMinutes": settings.openLeadMinutes}
    )


@group.tool
async def get_notification_preferences() -> dict:
    """Get the notification preferences of the logged-in user."""
    return await api().get("/notifications/preferences")


@group.tool
async def set_notification_preferences(preferences: list[dict[str, Any]]) -> dict:
    """Replace the notification preferences of the logged-in user.

    Use the same shape that `get_notification_preferences` returns.
    """
    return await api().put(
        "/notifications/preferences", json={"preferences": preferences}
    )


@group.tool
async def list_push_devices() -> dict:
    """List the devices of the logged-in user that get push notifications, newest first.

    A device is added only in the browser, because the browser makes the subscription.
    """
    return await api().get("/push/devices")


@group.tool
async def remove_push_device(device_id: str) -> dict:
    """Remove one push device of the logged-in user. It gets no push after that."""
    return await api().delete(f"/push/devices/{device_id}")


@group.tool
async def get_push_preferences() -> dict:
    """Get the push switch of every notification kind of the logged-in user.

    The push switches are separate from the mail switches of
    `get_notification_preferences`.
    """
    return await api().get("/push/preferences")


@group.tool
async def set_push_preferences(preferences: list[dict[str, Any]]) -> dict:
    """Set the push switches of the logged-in user; the server returns all of them.

    Use the same shape that `get_push_preferences` returns.
    """
    return await api().put("/push/preferences", json={"preferences": preferences})


@group.tool
async def get_site_config() -> dict:
    """Get the active site and branding config and its version."""
    return await api().get("/admin/site-config")


@group.tool
async def set_site_config(branding: dict[str, Any]) -> dict:
    """Save the branding as the new active version. It applies at once.

    Use the same shape as `branding` in `get_site_config`. Requires admin.site.
    """
    return await api().put("/admin/site-config", json=branding)


@group.tool
async def list_ui_languages() -> dict:
    """List the extra UI languages, inactive ones included. Requires admin.translations.

    DE and EN are built in and are not in the list. An extra language shows its own
    text of a key, else the EN text, else the DE text.
    """
    return await api().get("/admin/translations/languages")


@group.tool
async def create_ui_language(language: S.UiLanguageCreate) -> dict:
    """Add an extra UI language. Requires admin.translations.

    It starts inactive unless `active` is true. Only an active language shows in the
    language switch. 409 `language_builtin` for `de`/`en`, 409 `language_exists`.
    """
    return await api().post("/admin/translations/languages", json=dump_create(language))


@group.tool
async def update_ui_language(code: str, patch: S.UiLanguageUpdate) -> dict:
    """Rename an extra UI language or switch it on or off. Requires admin.translations."""
    return await api().patch(f"/admin/translations/languages/{code}", json=dump_patch(patch))


@group.tool
async def delete_ui_language(code: str) -> dict:
    """Delete an extra UI language and all its texts. Requires admin.translations."""
    return await api().delete(f"/admin/translations/languages/{code}")


@group.tool
async def get_builtin_ui_texts(
    prefix: str | None = None,
    locale: str | None = None,
    untranslated: bool = False,
) -> dict:
    """Get the built-in DE and EN UI texts by key. Requires admin.translations.

    Translate from these texts. Each row is `{key, de, en, own}`: `en` is null where
    EN shows the DE text, and `own` is the own text of `locale` (null without one).
    `prefix` keeps the keys that start with it (for example `meetings.`), because the
    whole catalog has about 4000 keys. `untranslated` needs `locale` and keeps the
    keys without an own text in it, so it lists the open work of a language.
    """
    return await api().get(
        "/admin/translations/builtin",
        params=params(prefix=prefix, locale=locale, untranslated=untranslated or None),
    )


@group.tool
async def get_ui_texts(locale: str) -> dict:
    """Get the own texts of one locale: key to text. Requires admin.translations.

    A key without an own text shows the built-in text and is absent here. `locale` is
    `de`, `en` or the code of an extra language.
    """
    return await api().get(f"/admin/translations/texts/{locale}")


@group.tool
async def set_ui_texts(locale: str, changes: dict[str, str | None]) -> dict:
    """Change the own texts of one locale. Requires admin.translations.

    `changes` maps a key to the new text, or to null (or a blank text) for the
    built-in text. A key that `changes` leaves out stays. A text must keep exactly the
    `{placeholders}` of the built-in text. A key outside the catalog (422
    `unknown_key`) or a placeholder difference (422 `placeholder_mismatch`) refuses
    the whole save. The texts apply at the next start of the app.
    """
    return await api().put(f"/admin/translations/texts/{locale}", json={"changes": changes})


@group.tool
async def list_audit(
    action: str | None = None,
    actor: str | None = None,
    since: str | None = None,
    until: str | None = None,
    before: int | None = None,
    limit: int | None = None,
) -> dict:
    """Read the audit log.

    The log is keyset-paged. Pass the smallest id you have seen as `before` to get
    the next page. Give `since` and `until` as ISO datetimes. Requires audit.read.
    """
    return await api().get(
        "/admin/audit",
        params=params(
            action=action, actor=actor, since=since, until=until,
            before=before, limit=limit,
        ),
    )


@group.tool
async def get_forced_status_report(
    date_from: str | None = None, date_to: str | None = None
) -> dict:
    """Count the forced status changes per reason and per path (from, to state).

    `date_from` and `date_to` are ISO dates, both days included; the default is the
    last 90 days. A forced change without a reason counts as `none`. A frequent path
    is a way that the flow lacks. Requires audit.read.
    """
    return await api().get(
        "/admin/forced-status", params=params(**{"from": date_from, "to": date_to})
    )


@group.tool
async def list_forced_status_changes(
    date_from: str | None = None,
    date_to: str | None = None,
    reason: str | None = None,
    from_key: str | None = None,
    to_key: str | None = None,
) -> list:
    """List the forced status changes behind a count of `get_forced_status_report`.

    `reason` narrows to one reason key (`none` for no reason); `from_key` and `to_key`
    (state keys) narrow to one path. The newest first, at most 500. Requires
    audit.read.
    """
    return await api().get(
        "/admin/forced-status/events",
        params=params(
            **{"from": date_from, "to": date_to},
            reason=reason,
            fromKey=from_key,
            toKey=to_key,
        ),
    )


@group.tool
async def verify_audit_chain() -> dict:
    """Verify the hash chain of the audit log to find tampering. Requires audit.verify.

    The check runs live and stores nothing. It reads the whole log, so it is slow on a
    long log. To see the result of the last stored check, use
    `get_latest_audit_verification`.
    """
    return await api().get("/admin/audit/verify")


@group.tool
async def get_latest_audit_verification() -> dict | None:
    """Read the newest stored check of the audit hash chain. Requires audit.read.

    The worker checks the chain every night at 04:30 and after each restore. An admin
    can also start a check. The result holds `startedAt`, `finishedAt`, `valid`,
    `checked`, `brokenAt` and `reason` (the first break), `trigger`
    (cron/manual/restore) and `triggeredBy`. It is null before the first check.
    """
    return await api().get("/admin/audit/verify/latest")


def register(mcp: FastMCP) -> None:
    """Register the admin tool group."""
    group.register(mcp)
