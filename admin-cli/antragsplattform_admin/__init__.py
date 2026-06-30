"""antragsplattform admin-cli — fancy full-screen TUI to manage users, roles, OIDC
group-mappings and to view the audit log, talking to the Dockerised Postgres directly
(like ``scripts/remove-admin-role.sh``). Bypasses the API → no audit entry, no RBAC guards."""

__version__ = "0.1.0"
