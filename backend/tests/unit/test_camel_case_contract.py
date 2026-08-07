"""Every property in the OpenAPI contract must be camelCase.

A snake_case field passes both sides of a mocked unit test and fails only in the
browser, so the check reads the generated OpenAPI document instead.
"""

from __future__ import annotations

from app.main import app

# Properties that stay snake_case on purpose; the frontend reads them as they are.
_ALLOWED: frozenset[str] = frozenset(
    {
        # `Principal` in `frontend/src/app/core/api/models.ts` mirrors it field for field.
        "display_name",
        "session_manage_gremien",
        "has_scoped_budget_view",
        "in_substitute_pool",
        # `LogoutOut.logout_url`, mirrored the same way.
        "logout_url",
        # RFC 6749 fixes these wire names.
        "grant_type",
        "client_id",
        "code_verifier",
        "redirect_uri",
        "refresh_token",
        "error_description",
        # Multipart field names of the attachment upload; `mappers.ts` maps them.
        "field_key",
        "is_comparison_offer",
        # `MagicLinkVerifyOut` in the frontend models mirrors `application_id` as it is.
        "application_id",
    }
)


def test_the_openapi_contract_holds_no_snake_case_property() -> None:
    schemas = app.openapi().get("components", {}).get("schemas", {})
    offenders = sorted(
        f"{name}.{prop}"
        for name, schema in schemas.items()
        for prop in schema.get("properties", {})
        if "_" in prop and prop not in _ALLOWED
    )

    assert not offenders, "snake_case leaks into the JSON contract:\n" + "\n".join(
        offenders
    )
