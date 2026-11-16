---
id: "001121"
title: The profile page hides the claims of the token itself
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/auth/test_profile_claims.py:test_person_claims_hides_the_technical_claims_and_sorts"
  - "backend/tests/integration/modules/auth/test_auth_callback_persist.py:test_callback_persists_principal_then_me_returns_200"
implementation:
  - backend/app/modules/auth/profile.py
scope:
  - backend/app/modules/auth
---

# The profile page hides the claims of the token itself

The profile page (`F/administration/accounts/001120`) must not show the claims of the token
mechanics: `iss`, `aud`, `exp`, `iat`, `nbf`, `auth_time`, `nonce`, `at_hash`, `c_hash`,
`s_hash`, `azp`, `sid`, `jti`, `acr` and `amr`.

Reason: These claims describe the token, not the person, and tell the person nothing about
the profile.

Test: The unit test gives every one of these claims and gets none of them back. The
integration test finds no `iss` and no `nonce` on the page.
