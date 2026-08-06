"""Every property in the OpenAPI contract must be camelCase.

The house rule is camelCase in JSON on both sides. A model that misses it still
compiles on both sides and still passes a mocked unit test, because both mocks
agree with each other. It fails only in the browser, where the field reads
`undefined`.

`_CamelModel` in the admin schemas carries `populate_by_name` but no alias
generator, so a snake_case field needs an explicit `serialization_alias`. One
model missed it and served `webhook_id` where the frontend read `webhookId`.
This test reads the generated OpenAPI document, which is the real contract, and
fails on the next one.
"""

from __future__ import annotations

from app.main import app

# Properties that stay snake_case on purpose. The frontend reads these names as
# they are, so a change here is a breaking contract change on both sides.
_ALLOWED: frozenset[str] = frozenset(
    {
        # `MeOut` is a plain BaseModel, not a camel model. `Principal` in
        # `frontend/src/app/core/api/models.ts` mirrors it field for field.
        "display_name",
        "session_manage_gremien",
        "has_scoped_budget_view",
        "in_substitute_pool",
        # `LogoutOut.logout_url`, mirrored the same way.
        "logout_url",
        # RFC 6749 fixes the wire names of the token endpoint and of an OAuth
        # error. A camel name here would break every standard client.
        "grant_type",
        "client_id",
        "code_verifier",
        "redirect_uri",
        "refresh_token",
        "error_description",
        # Multipart field names of the attachment upload, plus the field the
        # response echoes. `ApiClient.uploadAttachment` writes and reads exactly
        # these names and maps them to camelCase in `mappers.ts`.
        "field_key",
        "is_comparison_offer",
        # The magic-link contract. `MagicLinkVerifyOut` in the frontend models
        # mirrors `application_id` as it is.
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
