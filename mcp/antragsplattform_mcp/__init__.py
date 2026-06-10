"""antragsplattform MCP server — exposes the platform API to agents.

Authentication is a standard OAuth2 Authorization-Code + PKCE *browser grant*: on the
first call the server opens the platform login in a browser, captures the code on a
loopback redirect, and exchanges it for a scoped bearer token (cached locally, refreshed
automatically). The platform URL is supplied at MCP setup via ``ANTRAGSPLATTFORM_URL``.
"""

__version__ = "0.1.0"
