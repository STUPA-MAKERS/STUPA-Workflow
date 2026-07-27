"""antragsplattform admin-cli — a full-screen command REPL on prompt_toolkit.

The REPL takes mouse and keyboard input. It manages users, roles and OIDC group-mappings,
and it reads the audit log. It talks to the Dockerized Postgres directly. That bypasses
the API, so it writes no audit entry and applies no RBAC guard. The CLI resolves the DB
connection from deploy/.env and from the port that the compose file publishes. See
`antragsplattform_admin.config`.
"""

__version__ = "0.2.0"
