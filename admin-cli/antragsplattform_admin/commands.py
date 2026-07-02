"""The fixed set of slash-commands, used for completion and the help screen."""

# Command name -> one-line description (shown in the completion menu).
BASE_COMMANDS: dict[str, str] = {
    "/users": "list users (optional search term)",
    "/user": "inspect / act on one user (selector when no argument)",
    "/roles": "list roles with permission + assignment counts",
    "/role": "inspect / act on one role",
    "/new-role": "create a role",
    "/mappings": "list OIDC group→role mappings",
    "/mapping": "inspect / act on one mapping",
    "/new-mapping": "create an OIDC group-mapping (form)",
    "/audit": "show the audit log (action= actor= target= limit=)",
    "/more": "load older audit entries",
    "/status": "connection, mode and entity counts",
    "/connect": "(re)connect to the database",
    "/clear": "clear the log",
    "/help": "show help",
    "/quit": "exit",
}

# The per-entity actions offered by /user, /role and /mapping.
USER_ACTIONS: tuple[str, ...] = (
    "show",
    "roles",
    "grant",
    "revoke",
    "activate",
    "deactivate",
    "delete",
)
ROLE_ACTIONS: tuple[str, ...] = ("show", "perms", "rename", "delete")
MAPPING_ACTIONS: tuple[str, ...] = ("show", "edit", "delete")

# Keys accepted by /audit key=value tokens.
AUDIT_KEYS: tuple[str, ...] = ("action=", "actor=", "target=", "limit=")

# Lines shown by ``/help``.
HELP_LINES: tuple[str, ...] = (
    "hover a row to highlight · click to pop out the full record · esc closes",
    "/users [search]              list users",
    "/user [term] [action]        show · roles · grant · revoke · (de)activate · delete",
    "/roles · /role [key] [act]   list roles · show · perms · rename · delete",
    "/new-role [key]              create a role",
    "/mappings · /mapping [grp]   list mappings · show · edit · delete",
    "/new-mapping                 create a mapping (form)",
    "/audit [k=v …]               action= actor= target= limit= (bare word = action)",
    "/more                        older audit entries · /status · /connect",
    "/clear · /help · /quit       Tab completes · PgUp/PgDn scroll · Ctrl-D exit",
)

__all__ = [
    "BASE_COMMANDS",
    "USER_ACTIONS",
    "ROLE_ACTIONS",
    "MAPPING_ACTIONS",
    "AUDIT_KEYS",
    "HELP_LINES",
]
