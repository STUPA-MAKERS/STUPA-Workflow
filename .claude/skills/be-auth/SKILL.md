---
name: be-auth
description: Backend identity and access. Covers OIDC/Keycloak login (Auth Code + PKCE), magic-link applicant sessions, server-side principal sessions, and RBAC (role/role_permission/role_assignment/group_mapping, time-bound delegation). Also an OAuth2 authorization server that issues scoped opaque tokens for MCP agents. Use when working on login/callback/logout, /auth/me, magic-links, sessions, RBAC permission resolution, OAuth scopes/consent/grants, or bootstrap admins in backend/app/modules/auth.
---

# Auth (Identity, RBAC, OIDC, OAuth2-AS) — `backend/app/modules/auth`

**Does:** Authenticates members through Keycloak OIDC (Authorization Code + PKCE) into server-side sessions. Authenticates applicants through single-use magic-links. Resolves app-side RBAC (roles → permissions, gremium-scoped and time-bound). Acts as an OAuth2 authorization server that mints scoped opaque access/refresh tokens for native and MCP clients. CRITICAL module (100% branch coverage gate).

**Key files:**
- `router.py` — `/auth` routes: OIDC login/callback, logout (RP-initiated), `/auth/me`, magic-link request/verify
- `service.py` — orchestration: magic-link issue/verify, OIDC callback (code→token→session), `upsert_principal`
- `models.py` — tables: `Principal`, `Role`, `RolePermission`, `RoleAssignment`, `AuthSession`, `GroupMapping`
- `principal.py` — leaf `Principal`/`Applicant` dataclasses + `.has()` (breaks the deps↔auth import cycle). `app.deps` re-exports them
- `rbac.py` — `resolve_principal()`: principal row → roles/permissions/groups (the single RBAC resolution path)
- `oidc.py` — Keycloak primitives: PKCE/state/nonce, authorize URL, code exchange, `id_token` JWKS verify (RS256), end-session URL
- `sessions.py` — signed cookies (itsdangerous): opaque `sid` principal session, stateless applicant token, OIDC-tx, OAuth-tx
- `tokens.py` — magic-link token CSPRNG + HMAC-SHA256(pepper) hashing, constant-time verify
- `bootstrap.py` — idempotent first-admin grant by `sub`/verified-email. It always grants the global `member` role
- `oauth.py` — DB-free OAuth2 helpers: scope catalog, PKCE S256 verify, token gen/SHA-256 hash, scope→permission mapping
- `oauth_service.py` — OAuth2-AS I/O: mint authorization code, exchange code→tokens, refresh rotation, `resolve_access_token`
- `oauth_models.py` — `OAuthAuthorizationCode`, `OAuthToken` (hashes only, never plaintext)
- `oauth_router.py` — `/oauth` routes: authorize/finish/consent/token, grants list/revoke + `.well-known` AS/PR metadata
- `mcp_router.py` — `/mcp` self-service: client config snippet + `mcp/` source package `.tar.gz` (gated on `mcp.use`)

**Domain / data model:**
- `principal` — OIDC subject. `sub` (unique), `email` (CITEXT, PII), `display_name`, `oidc_groups` (JSONB cache), `last_login`, `active` (deactivated → login refused, fail-closed), `calendar_token` (unique index, iCal feed).
- `role` (`key` unique, `name_i18n`) / `role_permission` (PK `role_id`+`permission`, permission strings) — app roles are the source of truth. Key roles: `admin` (bypass — has all permissions), `member` (every user always holds it).
- `role_assignment` — principal→role with optional `gremium_id` scope and `valid_from`/`valid_until` window. `granted_by` (`"bootstrap"` for auto-grants), `delegated_by` (self-delegation marker → cast-block + "my delegations"), `delegate_voting`.
- `group_mapping` — OIDC group → role, optionally gremium-scoped (convenience layer on top of assignments).
- `auth_session` — server session for an OIDC principal: opaque `sid` (signed into HttpOnly cookie), `principal_id`, `expires_at`, server-held `refresh_token`/`id_token`. No JWT in JS.
- `oauth_authorization_code` — short-lived single-use PKCE-bound code (`code_hash`, `code_challenge` S256, `scope`, `access_ttl_seconds`, `used_at`).
- `oauth_token` — opaque access+refresh pair, hashes only (`access_token_hash`/`refresh_token_hash`), `scope`, `access_expires_at`/`refresh_expires_at`, `revoked_at`. Refresh rotation writes a new row and sets `revoked_at` on the old one.
- Applicant scope enum: `edit` | `view` (edit covers view, magic-link single_use when scope≠edit).
- OAuth scopes (`oauth.SCOPES`): `read`, `applications:write`, `votes:write`, `budget:write`, `meetings:write`, `forms:write`, `flows:write`, `admin:write`. Lifetimes 1h/8h/1d/30d/90d (cap `MAX_LIFETIME_SECONDS`=90d, no never-expire).

**API surface:**
- `GET /api/auth/login` — 307 → Keycloak authorize. State, verifier and nonce ride in the signed `oidc_tx` cookie
- `GET /api/auth/callback` — code→token→session. Sets the `sid` cookie. Redirects to `/api/oauth/finish` when an OAuth tx is in flight
- `POST /api/auth/logout` — kill session + cookie (idempotent), returns Keycloak `end_session` URL for SSO logout
- `GET /api/auth/me` — principal + roles/permissions/groups + member/manage gremien, scoped-budget & substitute-pool flags
- `POST /api/auth/magic-link` — 202 always (anti-enumeration, constant time, delivery in background task)
- `POST /api/auth/magic-link/verify` — token → applicant session cookie. Expired or used → 410
- `GET /api/oauth/authorize` — validate client_id + loopback redirect_uri + S256 challenge, stash tx, start OIDC login
- `GET /api/oauth/finish` — post-login → redirect to in-app `/oauth/consent`
- `GET /api/oauth/consent-request` — pending request (scopes + which the user holds + lifetimes)
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
- Test doubles for `Principal` must model the admin bypass. A fake `has = lambda p: p in perms` makes a `roles=["admin"]` principal behave unlike production, so a test can pass against behaviour that never existed.
- `vote.cast` is in `FORBIDDEN_PERMISSIONS`. Every scope resolution strips it. MCP agents can manage votes, but they can never cast a ballot. Votes are reserved for humans.
- RBAC resolution (`rbac.resolve_principal`) merges time-validated `role_assignment` and `group_mapping` rows. The assignment or mapping `gremium_id` becomes a group key, which drives `require_group`. A DB-side `valid_from/until` may be naive, so `_as_aware` coerces it to aware UTC before the compare. Gremium voting eligibility comes from `gremium_membership` rows whose `gremium_role` holds `vote.cast`.
- Anti-enumeration: `/auth/magic-link` always answers 202 with a constant body. The real DB work and the delivery run in a BackgroundTask (constant response time, no timing leak). The magic-link mail goes through the notifications mail-queue (arq). See `be-notifications`.
- `email_verified` matters: the email-based admin bootstrap counts only on a fresh verified `id_token` claim (`ensure_admin_for_principal`). The startup sweep (`ensure_bootstrap_admins`) uses `sub` only. Bootstrap grants are global and unscoped, with `granted_by="bootstrap"`.
- Service functions DO NOT commit. The router or the caller owns the transaction (callback/verify/logout commit explicitly, get_session never auto-commits).
- OAuth: the server accepts only `S256` PKCE and `http` loopback redirect_uris (RFC 8252). The client must equal `oauth_mcp_client_id`. An invalid redirect gives 400 (never redirect to it). `/oauth/token` returns RFC-6749 error JSON (`x-error-contract: oauth`), exempt from the app-wide problem+json. Codes are single-use. Refresh rotates.
- Request-time token resolution lives in `app.deps`, not in this module (`get_current_principal` through `oauth_service.resolve_access_token` for `apat_`-prefixed bearers, `get_current_applicant` through `sessions.load_applicant_token`). `app.deps` re-exports `Principal`/`Applicant`.
- See the house rules in the `conventions` skill (tz-aware, RFC-9457 problem+json, whitelist guards/no-eval, coverage gates).

**Related:** be-admin, be-delegations, be-notifications, be-applications, be-flow
