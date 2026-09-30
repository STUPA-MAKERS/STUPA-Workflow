---
name: be-auth
description: Backend identity and access. Covers OIDC login against any discovery-capable IdP (Auth Code + PKCE), magic-link applicant sessions, server-side principal sessions, and RBAC (role/role_permission/role_assignment/group_mapping, time-bound delegation). Also an OAuth2 authorization server that issues scoped opaque tokens for MCP agents. Use when working on login/callback/logout, /auth/me, magic-links, sessions, RBAC permission resolution, OAuth scopes/consent/grants, or bootstrap admins in backend/app/modules/auth.
---

# Auth (Identity, RBAC, OIDC, OAuth2-AS) — `backend/app/modules/auth`

**Does:** Authenticates members through OIDC (Authorization Code + PKCE) against any IdP with a discovery document (authentik in production) into server-side sessions. Authenticates applicants through single-use magic-links. Resolves app-side RBAC (roles → permissions, gremium-scoped and time-bound). Acts as an OAuth2 authorization server that mints scoped opaque access/refresh tokens for native and MCP clients. CRITICAL module (100% branch coverage gate).

**Key files:**
- `router.py` — `/auth` routes: OIDC login/callback, logout (RP-initiated), `/auth/me`, magic-link request/verify
- `service.py` — orchestration: magic-link issue/verify, OIDC callback (code→token→session), `upsert_principal`
- `models.py` — tables: `Principal`, `Role`, `RolePermission`, `RoleAssignment`, `AuthSession`, `GroupMapping`
- `principal.py` — leaf `Principal`/`Applicant` dataclasses + `.has()` (breaks the deps↔auth import cycle). `app.deps` re-exports them
- `rbac.py` — `resolve_principal()`: principal row → roles/permissions/groups (the single RBAC resolution path)
- `oidc.py` — OIDC primitives: discovery (`discover`, TTL-cached per issuer), PKCE/state/nonce, authorize URL, code exchange, `id_token` JWKS verify (RS256), end-session URL
- `sessions.py` — signed cookies (itsdangerous): opaque `sid` principal session, stateless applicant token, OIDC-tx, OAuth-tx
- `tokens.py` — magic-link token CSPRNG + HMAC-SHA256(pepper) hashing, constant-time verify
- `service.oidc_callback` also calls `admin.membership_sync.sync_principal_memberships` after the upsert, so gremium memberships follow the IdP groups from each login on.
- `bootstrap.py` — idempotent first-admin grant by `sub`/verified-email. It always grants the global `member` role
- `oauth.py` — DB-free OAuth2 helpers: scope catalog, PKCE S256 verify, token gen/SHA-256 hash, scope→permission mapping
- `oauth_service.py` — OAuth2-AS I/O: mint authorization code, exchange code→tokens, refresh rotation, `resolve_access_token`
- `oauth_models.py` — `OAuthAuthorizationCode`, `OAuthToken` (hashes only, never plaintext)
- `oauth_router.py` — `/oauth` routes: authorize/finish/consent/token, grants list/revoke + `.well-known` AS/PR metadata
- `mcp_router.py` — `/mcp` self-service: client config snippet + `mcp/` source package `.tar.gz` (gated on `mcp.use`)

**Domain / data model:**
- `principal` — OIDC subject. `sub` (unique), `email` (CITEXT, PII), `display_name`, `oidc_groups` (JSONB cache, refreshed at every login; drives `group_mapping` and the gremium-membership sync), `last_login`, `active` (deactivated → login refused, fail-closed), `calendar_token` (unique index, iCal feed).
- `role` (`key` unique, `name_i18n`) / `role_permission` (PK `role_id`+`permission`, permission strings) — app roles are the source of truth. Key roles: `admin` (bypass — has all permissions), `member` (every user always holds it).
- `role_assignment` — principal→role with optional `gremium_id` scope and `valid_from`/`valid_until` window. `granted_by` (`"bootstrap"` for auto-grants), `delegated_by` (self-delegation marker → cast-block + "my delegations"), `delegate_voting`. Only the bootstrap writes it now (`admin` from `BOOTSTRAP_ADMIN_*`, implicit `member`). There is no admin write API; global roles come from `group_mapping`.
- `group_mapping` — OIDC group → global role. NO gremium scope (column dropped in `097f61e33e3c`). The ONLY source of non-bootstrap global roles. Resolved live per request from the cached `principal.oidc_groups`.
- `auth_session` — server session for an OIDC principal: opaque `sid` (signed into HttpOnly cookie), `principal_id`, `expires_at`, server-held `refresh_token`/`id_token`. No JWT in JS.
- `oauth_authorization_code` — short-lived single-use PKCE-bound code (`code_hash`, `code_challenge` S256, `scope`, `access_ttl_seconds`, `used_at`).
- `oauth_token` — opaque access+refresh pair, hashes only (`access_token_hash`/`refresh_token_hash`), `scope`, `access_expires_at`/`refresh_expires_at`, `revoked_at`. Refresh rotation writes a new row and sets `revoked_at` on the old one.
- Applicant scope enum: `edit` | `view` (edit covers view, magic-link single_use when scope≠edit).
- OAuth scopes (`oauth.SCOPES`): `read`, `applications:write`, `votes:write`, `budget:write`, `meetings:write`, `forms:write`, `flows:write`, `admin:write`. Lifetimes 1h/8h/1d/30d/90d (cap `MAX_LIFETIME_SECONDS`=90d, no never-expire).
- A scope also caps the GREMIUM permissions: `meetings:write` = `session.manage` + `protocol.write` + `protocol.finalize`, `votes:write` = `vote.manage`. `read` holds the global `meeting.view_all`, so an admin token keeps the cross-gremium meeting view. The global keys `meeting.manage`, `protocol.finalize` and `application.create` are gone (migration `3a0b9672fcba`).

**API surface:**
- `GET /api/auth/login` — 307 → IdP authorize (503 when discovery fails). State, verifier and nonce ride in the signed `oidc_tx` cookie
- `GET /api/auth/callback` — code→token→session. Sets the `sid` cookie. Redirects to `/api/oauth/finish` when an OAuth tx is in flight
- `POST /api/auth/logout` — kill session + cookie (idempotent), returns the IdP `end_session_endpoint` URL for SSO logout (`null` when the IdP has none or discovery fails; the local session ends anyway)
- `GET /api/auth/me` — principal + roles/permissions/groups + member/manage gremien, `gremium_permissions` (gremium id → gremium keys of the active role, scope-capped), scoped-budget & substitute-pool flags
- `POST /api/auth/magic-link` — 202 always (anti-enumeration, constant time, delivery in background task)
- `POST /api/auth/magic-link/verify` — token → applicant session cookie. Expired or used → 410
- `GET /api/oauth/authorize` — validate client_id + loopback redirect_uri + S256 challenge, stash tx, start OIDC login
- `GET /api/oauth/finish` — post-login → redirect to in-app `/oauth/consent`
- `GET /api/oauth/consent-request` — pending request (scopes + which the user holds + lifetimes). A scope counts as held when the user holds one of its keys globally OR through a gremium role in any gremium
- `POST /api/oauth/consent` — mint code with chosen scope/lifetime (approve) or `access_denied` (deny). Requires `mcp.use`
- `POST /api/oauth/token` — `authorization_code`/`refresh_token` → scoped opaque token pair (RFC-6749 §5.2 error JSON, NOT problem+json)
- `GET /api/oauth/grants`, `DELETE /api/oauth/grants/{id}`, `DELETE /api/oauth/grants` — self-service grant list / revoke / revoke-all
- `GET /api/admin/oauth-grants`, `DELETE /api/admin/oauth-grants/{id}` — grants of ANY principal, `admin.users`. This is how an admin kills a leaked agent token. Both routes and the self-service ones share one revocation path in `oauth_service.py` (`load_grant`, `revoke_grant`, `revoke_all_grants`), so a second path cannot drift.
- `GET /.well-known/oauth-authorization-server`, `GET /.well-known/oauth-protected-resource` — RFC 8414 / 9728 discovery
- `GET /api/mcp/config`, `GET /api/mcp/package` — MCP client config + source tarball (gated `mcp.use`)

**Conventions & gotchas:**
- Tokens NEVER reach JS or response bodies. They live only in HttpOnly+Secure+SameSite=Lax cookies. The magic-link token rides the URL **fragment** (`#t=`), so it stays out of Referer, logs and history. The FE reads it and POSTs it to verify.
- The backend NEVER persists a plaintext token: magic-link = HMAC-SHA256(MAGIC_LINK_SECRET pepper), OAuth code/access/refresh = SHA-256. All compares are constant-time (`hmac.compare_digest`).
- `Principal.has()` is the single RBAC chokepoint. It checks the scope cap FIRST. A scoped OAuth token cannot reach a permission outside its scope, even for admin. It then applies the `admin` bypass, then the explicit permission. `scope_permissions=None` means unscoped (cookie session).
- **Never read `principal.roles` to decide a right.** `"admin" in principal.roles` looks equivalent to `principal.has(...)` for a cookie session and IS equivalent there — which is why it passes review and passes tests. It skips the scope cap, so an agent token issued to an admin acts as a full admin. This shipped: `assert_can_manage` in `voting/service.py` returned early on the role read, and a `read`-scoped token opened, closed and cancelled votes. Ask *which right* the check is about and call `has()` with it; the admin bypass inside `has` covers the admin case. Reading `principal.roles` is only correct when the question is genuinely about role identity, not about a permission, and such a site must say so in a comment.
- **Gremium permissions go through `gremium_ids_for(session, principal, perm)` and `admin_bypass(principal, perm)`** (`admin/gremium_roles.py`), never through the sub-based `gremium_ids_with_permission` on a request path. Gremium keys never enter `principal.permissions`, so `has()` cannot cap them; `Principal.scope_allows(perm)` does. The sub-based lookup stays only for system and roster paths (principal resolution, quorum count, delegation eligibility, mail recipients). Bug F16: a `read` token of a chair or of the minute-taker could manage the meeting and write the minutes.
- Test doubles for `Principal` must model the admin bypass. A fake `has = lambda p: p in perms` makes a `roles=["admin"]` principal behave unlike production, so a test can pass against behaviour that never existed.
- `vote.cast` is in `FORBIDDEN_PERMISSIONS`. Every scope resolution strips it. MCP agents can manage votes, but they can never cast a ballot. Votes are reserved for humans.
- RBAC resolution (`rbac.resolve_principal`) merges time-validated `role_assignment` (bootstrap only) and `group_mapping` rows. Gremium rights come only from the derived `gremium_membership` (`vote:<gremium_id>` key for `vote.cast`); a global role or a raw OIDC claim never grants a gremium right. A DB-side `valid_from/until` may be naive, so `_as_aware` coerces it to aware UTC before the compare.
- Anti-enumeration: `/auth/magic-link` always answers 202 with a constant body. The real DB work and the delivery run in a BackgroundTask (constant response time, no timing leak). The magic-link mail goes through the notifications mail-queue (arq). See `be-notifications`.
- `email_verified` matters: the email-based admin bootstrap counts only on a fresh verified `id_token` claim (`ensure_admin_for_principal`). The startup sweep (`ensure_bootstrap_admins`) uses `sub` only. Bootstrap grants are global and unscoped, with `granted_by="bootstrap"`.
- Service functions DO NOT commit. The router or the caller owns the transaction (callback/verify/logout commit explicitly, get_session never auto-commits).
- OAuth: the server accepts only `S256` PKCE and `http` loopback redirect_uris (RFC 8252). The client must equal `oauth_mcp_client_id`. An invalid redirect gives 400 (never redirect to it). `/oauth/token` returns RFC-6749 error JSON (`x-error-contract: oauth`), exempt from the app-wide problem+json. Codes are single-use. Refresh rotates.
- Request-time token resolution lives in `app.deps`, not in this module (`get_current_principal` through `oauth_service.resolve_access_token` for `apat_`-prefixed bearers, `get_current_applicant` through `sessions.load_applicant_token`). `app.deps` re-exports `Principal`/`Applicant`.
- **Endpoints come from discovery, never from a path convention.** `oidc.discover` reads `{issuer}/.well-known/openid-configuration` and requires its `issuer` to equal `oidc_issuer` exactly. The `iss` check of the `id_token` is exact too, so `OIDC_ISSUER` must be the IdP's value verbatim — authentik's ends in `/`, Keycloak's does not. `OidcUnavailableError` (discovery, token or JWKS unreachable, bad document) maps to 503; any other `OidcError` maps to 400. Tests clear `oidc._discovery_cache` and `oidc._jwks_cache`.
- See the house rules in the `conventions` skill (tz-aware, RFC-9457 problem+json, whitelist guards/no-eval, coverage gates).

**Related:** be-admin, be-delegations, be-notifications, be-applications, be-flow
