---
id: "001120"
title: The account area has a profile page with the SSO claims
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/auth/test_profile_claims.py:test_id_token_claims_reads_the_payload"
  - "backend/tests/unit/modules/auth/test_profile_claims.py:test_person_claims_without_a_token_uses_the_stored_fields"
  - "backend/tests/integration/modules/auth/test_auth_callback_persist.py:test_callback_persists_principal_then_me_returns_200"
  - "frontend/src/app/pages/account/profile.component.spec.ts:AccountProfileComponent"
  - "frontend/src/app/layout/account-menu/account-menu.component.spec.ts:AppAccountMenuComponent"
implementation:
  - backend/app/modules/auth/profile.py
  - backend/app/modules/account/router.py
  - frontend/src/app/pages/account/profile.component.ts
  - frontend/src/app/pages/account/account-pages.ts
  - frontend/src/app/layout/account-menu/account-menu.component.ts
scope:
  - backend/app/modules/auth
  - backend/app/modules/account
  - frontend/src/app/pages/account
  - frontend/src/app/layout/account-menu
---

# The account area has a profile page with the SSO claims

The account area must have the page "Profil" at `/account/profile`. Its entry must be the first
entry of the account menu and of the account navigation. The page must show, read only, every
claim of the `id_token` of the current session, one row per claim, and the time of the last
login. A claim that the catalog knows must show its label, and any other claim must show its
name. The page must not store a new value: the claims come from the token that the session
already keeps. Without such a token, as for an OAuth bearer request, the page must show the
stored subject, name, e-mail address and groups.

An e-mail login session (`F/administration/accounts/000583`) has no account and no account
menu, so it has no profile page.

Reason: A person wants to see what the platform got from the SSO about them, for example
which groups give their roles.

Test: The unit tests read the claims of a token and fall back to the stored fields. The
integration test logs in through the callback and reads `GET /api/auth/me/profile`. The
frontend tests show the rows and the menu entry.
