"""Auth module: OIDC login, sessions, RBAC and OAuth2 for MCP.

The login of an applicant (magic link, e-mail login) is in `applications`, and the route
`/auth/me` is in `account`, because `auth` imports no higher module
(§S/backend/python/000649).
"""
