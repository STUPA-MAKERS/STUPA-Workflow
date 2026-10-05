---
name: be-avatars
description: Gravatar proxy for person avatars — GET /api/principals/{id}/avatar and /api/principals/me/avatar fetch the Gravatar image (SHA-256 of the e-mail, d=404) from the fixed host gravatar.com through the webhook SSRF guard, cache hit and miss in Redis, and answer the bytes with ETag/Cache-Control or a problem+json 404. Admin switch gravatarEnabled in the site-config branding. Use when working on avatars, Gravatar, the avatar cache, the avatar rate limit, or the frontend app-avatar image in backend/app/modules/avatars.
---

# Avatars (Gravatar proxy) — `backend/app/modules/avatars`

**Does:** Serves the Gravatar image of a principal from our own origin. The browser never
contacts Gravatar, and neither the e-mail address nor its hash reaches the client. No CSP
change: the image comes from `'self'`. A person without a Gravatar gets a 404, and the
frontend shows the initials.

**Key files:**
- `gravatar.py` — `gravatar_hash` (SHA-256 of the trimmed, lower-case e-mail), `size_bucket`
  (64/128/256), `sniff_avatar` (PNG/JPEG/GIF/WebP magic bytes only; SVG, HTML and icons are a
  miss), `AvatarImage` (ETag from the bytes), `HttpGravatarFetcher` (resolve, SSRF check,
  pin the IP, `Host` + SNI `gravatar.com`, no redirects, one total deadline, 512 KiB cap).
- `cache.py` — `RedisAvatarCache` on the shared anti-abuse Redis client. Key
  `avatar:v1:<hash>:<size>`. Value `0` = miss, `1<mime>\n<bytes>` = image. Fails open.
- `service.py` — `gravatar_enabled` (active site config, default on), e-mail lookup by id or
  `sub`, `load_avatar` (cache, then fetch, then cache the result).
- `router.py` — the two routes, the per-principal throttle, the response headers.

**API surface:**
- `GET /api/principals/{principal_id}/avatar?s=<1..512>` — any logged-in principal (an
  applicant session gets 401). 200 image (`Cache-Control: private, max-age=<cache ttl>`,
  strong `ETag`), 304 on a matching `If-None-Match`, 404 `avatar_not_found` (unknown id, no
  e-mail, no Gravatar, failed fetch: `max-age=3600`; switch off: `max-age=300`), 422 bad id or
  size, 429 `rate_limited`.
- `GET /api/principals/me/avatar` — the same for the own row (by `sub`), plus
  `Vary: Cookie, Authorization`, because the URL is the same for every user.

**Settings:** `RL_AVATAR_PER_HOUR` (1200, per principal `sub`), `GRAVATAR_TIMEOUT_SECONDS` (3),
`GRAVATAR_CACHE_TTL_SECONDS` (86400, image and 404), `GRAVATAR_ERROR_TTL_SECONDS` (300, a
timeout or a 5xx of Gravatar, so a short outage heals itself). Admin switch:
`Branding.gravatar_enabled` (`gravatarEnabled`, default `True`, versioned with the site config;
the public `/api/site-config` carries it, so the frontend does not ask when it is off).

**Conventions & gotchas:**
- The URL is never user input: constant host, hex hash, bucketed size. The SSRF guard still
  runs (`webhooks.ssrf.assert_allowed_url` with allowlist `gravatar.com`, then `pin_url`),
  against a DNS answer that points at an internal address.
- Never pass Gravatar's headers or its `Content-Type` on. The type comes from the sniffed
  bytes; anything else is a miss.
- `deploy/web/nginx.conf` maps the avatar path to an empty `$ap_cache_control`, so nginx does
  not add `no-cache`. Without that the browser asks again on every list row.
- The api container needs outbound HTTPS to `gravatar.com` (see `deploy`).
- Frontend: `app-avatar` (`shared/ui/avatar`) takes `principalId` (an id or `'me'`). It puts
  the image over the initials and drops it on an error; `AvatarService` remembers the failed
  ids per session. `ActorOut.principalId` (be-applications: `actorInfo`, `changedByInfo`,
  `authorInfo`) gives the comment author avatar its id; only `kind=principal` carries it, so
  the applicant view never gets a member id. The history shows no avatars.

**Related:** be-auth, be-admin, be-webhooks, be-antiabuse, frontend, deploy
