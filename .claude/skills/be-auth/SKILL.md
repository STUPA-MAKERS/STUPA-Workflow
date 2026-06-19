---
name: be-auth
description: Backend identity & access — OIDC/Keycloak login (Auth Code + PKCE), magic-link applicant sessions, server-side principal sessions, RBAC (role/role_permission/role_assignment/group_mapping, time-bound delegation), and an OAuth2 authorization server issuing scoped opaque tokens for MCP agents. Use when working on login/callback/logout, /auth/me, magic-links, sessions, RBAC permission resolution, OAuth scopes/consent/grants, or bootstrap admins in backend/app/modules/auth.
---

# Auth (Identity, RBAC, OIDC, OAuth2-AS) — `backend/app/modules/auth`

**Does:** Authenticates members via Keycloak OIDC (Authorization Code + PKCE) into server-side sessions, authenticates applicants via single-use magic-links, resolves app-side RBAC (roles → permissions, gremium-scoped + time-bound), and acts as an OAuth2 authorization server minting scoped opaque access/refresh tokens for native/MCP clients. CRITICAL module (100% branch coverage gate).

**Key files:**
- `router.py` — `/auth` routes: OIDC login/callback, logout (RP-initiated), `/auth/me`, magic-link request/verify
- `service.py` — orchestration: magic-link issue/verify, OIDC callback (code→token→session), `upsert_principal`
- `models.py` — tables: `Principal`, `Role`, `RolePermission`, `RoleAssignment`, `AuthSession`, `GroupMapping`
- `principal.py` — leaf `Principal`/`Applicant` dataclasses + `.has()` (breaks deps↔auth import cycle); re-exported by `app.deps`
- `rbac.py` — `resolve_principal()`: principal row → roles/permissions/groups (the single RBAC resolution path)
- `oidc.py` — Keycloak primitives: PKCE/state/nonce, authorize URL, code exchange, `id_token` JWKS verify (RS256), end-session URL
- `sessions.py` — signed cookies (itsdangerous): opaque `sid` principal session, stateless applicant token, OIDC-tx, OAuth-tx
- `tokens.py` — magic-link token CSPRNG + HMAC-SHA256(pepper) hashing, constant-time verify
- `bootstrap.py` — idempotent first-admin grant by `sub`/verified-email; always-grant global `member` role
- `oauth.py` — DB-free OAuth2 helpers: scope catalogue, PKCE S256 verify, token gen/SHA-256 hash, scope→permission mapping
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
- `oauth_token` — opaque access+refresh pair, hashes only (`access_token_hash`/`refresh_token_hash`), `scope`, `access_expires_at`/`refresh_expires_at`, `revoked_at`; refresh rotation writes a new row + sets old `revoked_at`.
- Applicant scope enum: `edit` | `view` (edit covers view; magic-link single_use when scope≠edit).
- OAuth scopes (`oauth.SCOPES`): `read`, `applications:write`, `votes:write`, `budget:write`, `meetings:write`, `forms:write`, `flows:write`, `admin:write`. Lifetimes 1h/8h/1d/30d/90d (cap `MAX_LIFETIME_SECONDS`=90d, no never-expire).

**API surface:**
- `GET /api/auth/login` — 307 → Keycloak authorize; state/verifier/nonce in signed `oidc_tx` cookie
- `GET /api/auth/callback` — code→token→session; sets `sid` cookie; redirects to `/api/oauth/finish` if an OAuth tx is in flight
- `POST /api/auth/logout` — kill session + cookie (idempotent), returns Keycloak `end_session` URL for SSO logout
- `GET /api/auth/me` — principal + roles/permissions/groups + member/manage gremien, scoped-budget & substitute-pool flags
- `POST /api/auth/magic-link` — 202 always (anti-enumeration, constant time, delivery in background task)
- `POST /api/auth/magic-link/verify` — token → applicant session cookie; expired/used → 410
- `GET /api/oauth/authorize` — validate client_id + loopback redirect_uri + S256 challenge, stash tx, start OIDC login
- `GET /api/oauth/finish` — post-login → redirect to in-app `/oauth/consent`
- `GET /api/oauth/consent-request` — pending request (scopes + which the user holds + lifetimes)
- `POST /api/oauth/consent` — mint code with chosen scope/lifetime (approve) or `access_denied` (deny); requires `mcp.use`
- `POST /api/oauth/token` — `authorization_code`/`refresh_token` → scoped opaque token pair (RFC-6749 §5.2 error JSON, NOT problem+json)
- `GET /api/oauth/grants`, `DELETE /api/oauth/grants/{id}`, `DELETE /api/oauth/grants` — self-service grant list / revoke / revoke-all
- `GET /.well-known/oauth-authorization-server`, `GET /.well-known/oauth-protected-resource` — RFC 8414 / 9728 discovery
- `GET /api/mcp/config`, `GET /api/mcp/package` — MCP client config + source tarball (gated `mcp.use`)

**Conventions & gotchas:**
- Tokens NEVER reach JS or response bodies — only HttpOnly+Secure+SameSite=Lax cookies. Magic-link token rides the URL **fragment** (`#t=`) so it stays out of Referer/logs/history; FE reads it and POSTs to verify.
- Plaintext tokens are NEVER persisted: magic-link = HMAC-SHA256(MAGIC_LINK_SECRET pepper), OAuth code/access/refresh = SHA-256. All compares are constant-time (`hmac.compare_digest`).
- `Principal.has()` is the single RBAC chokepoint: scope-cap checked FIRST (a scoped OAuth token can't reach a permission outside its scope, even for admin), then `admin` bypass, then explicit permission. `scope_permissions=None` means unscoped (cookie session).
- `vote.cast` is in `FORBIDDEN_PERMISSIONS` — stripped from every scope resolution; MCP agents can manage votes but can never cast a ballot (votes are reserved for humans).
- RBAC resolution (`rbac.resolve_principal`) merges time-validated `role_assignment` + `group_mapping`; assignment/mapping `gremium_id` becomes a group key (drives `require_group`). DB-side `valid_from/until` may be naive → coerced to aware-UTC (`_as_aware`) before comparing. Gremium voting eligibility comes from `gremium_membership` rows whose `gremium_role` has `vote.cast`.
- Anti-enumeration: `/auth/magic-link` always 202 with constant body; the actual DB work + delivery run in a BackgroundTask (constant response time, no timing leak). Magic-link mail goes via the notifications mail-queue (arq); see `be-notifications`.
- `email_verified` matters: email-based admin bootstrap only counts on a fresh verified `id_token` claim (`ensure_admin_for_principal`); the startup sweep (`ensure_bootstrap_admins`) uses `sub` only. Bootstrap grants are global, unscoped, `granted_by="bootstrap"`.
- Service functions DON'T commit — the router/caller owns the transaction (callback/verify/logout commit explicitly; get_session never auto-commits).
- OAuth: only `S256` PKCE and `http` loopback redirect_uris (RFC 8252) accepted; client must equal `oauth_mcp_client_id`. Invalid redirect → 400 (never redirect to it). `/oauth/token` returns RFC-6749 error JSON (`x-error-contract: oauth`), exempt from app-wide problem+json. Codes are single-use; refresh rotates.
- Request-time token resolution lives in `app.deps` (`get_current_principal` via `oauth_service.resolve_access_token` for `apat_`-prefixed bearers; `get_current_applicant` via `sessions.load_applicant_token`), not in this module. `Principal`/`Applicant` are re-exported from `app.deps`.
- See house rules via the `conventions` skill (tz-aware, RFC-9457 problem+json, whitelist guards/no-eval, coverage gates).

**Related:** be-admin, be-delegations, be-notifications, be-applications, be-flow
