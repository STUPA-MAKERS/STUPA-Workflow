"""antragsplattform MCP server that exposes the platform API to agents.

Authentication uses a standard OAuth2 Authorization-Code + PKCE browser grant. On the
first call the server opens the platform login in a browser. It captures the code on a
loopback redirect and exchanges it for a scoped bearer token. The server caches the token
locally and refreshes it automatically. Set the platform URL at MCP setup with
`ANTRAGSPLATTFORM_URL`.
"""

__version__ = "0.1.0"
