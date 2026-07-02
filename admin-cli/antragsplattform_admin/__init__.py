"""antragsplattform admin-cli — a full-screen command REPL (prompt_toolkit, mouse +
keyboard) to manage users, roles and OIDC group-mappings and to read the audit log,
talking to the Dockerised Postgres directly. Bypasses the API → no audit entry, no
RBAC guards. The DB connection is resolved automatically from deploy/.env and the
compose file's published port (see :mod:`antragsplattform_admin.config`)."""

__version__ = "0.2.0"
