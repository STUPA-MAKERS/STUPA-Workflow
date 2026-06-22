# antragsplattform MCP server

An [MCP](https://modelcontextprotocol.io) server that lets agents act on the
antragsplattform via its HTTP API. Authentication is a standard OAuth2
Authorization-Code + PKCE **browser grant**: on the first tool call the server opens the
platform login in your browser, captures the result on a loopback redirect, and exchanges
it for a scoped bearer token. The token is cached locally and refreshed automatically.

The agent acts **as the logged-in user**: every action is still authorized server-side by
that user's RBAC permissions, intersected with the granted OAuth scope.

## Setup

Requires Python ≥ 3.11. Install (editable) from this directory:

```bash
pip install -e .
```

Configure it in your MCP client. The platform URL is supplied via `ANTRAGSPLATTFORM_URL`:

```json
{
  "mcpServers": {
    "antragsplattform": {
      "command": "antragsplattform-mcp",
      "env": {
        "ANTRAGSPLATTFORM_URL": "https://antrag.example.org",
        "ANTRAGSPLATTFORM_SCOPE": "read applications:write votes:write"
      }
    }
  }
}
```

- `ANTRAGSPLATTFORM_URL` (required) — the platform base URL.
- `ANTRAGSPLATTFORM_SCOPE` (optional) — space-separated OAuth scopes. Defaults to the full
  curated set (`read applications:write votes:write budget:write meetings:write`). Narrow
  this to limit what the agent can do.

The platform side must have OIDC configured and register this server's public client id
(`antragsplattform-mcp`, configurable via `OAUTH_MCP_CLIENT_ID`) — loopback redirect URIs
(`http://127.0.0.1:<port>/callback`) are accepted automatically for native clients.

## Scopes → permissions

| Scope | Grants (capped by the user's own rights) |
|-------|------------------------------------------|
| `read` | read applications, budgets, votes, meetings, audit, exports |
| `applications:write` | create / comment / transition applications |
| `votes:write` | create / open / close / cancel / manage votes (NEVER cast a ballot — human-only; `vote.cast` is in `FORBIDDEN_PERMISSIONS` and never grantable) |
| `budget:write` | book expenses, manage accounts |
| `meetings:write` | manage meetings & agendas |

## Tools

Auth: `login`, `whoami`, `logout`.
Applications: `list_applications`, `get_application`, `get_application_timeline`,
`create_application`, `comment_application`.
Flow: `list_transitions`, `fire_transition`.
Votes: `get_vote`, `create_application_vote`, `open_vote`, `close_vote`, `cancel_vote`, `create_meeting_vote`, `delete_meeting_vote` (no `cast_ballot` tool — casting a ballot is human-only).
Budget: `list_budgets`, `get_budget_applications`, `book_expense`.
Meetings: `list_meetings`, `get_meeting`.

## Token cache

Tokens live at `~/.config/antragsplattform-mcp/token-<hash>.json` (mode 600), one file per
platform URL. `logout` deletes it; the next call re-runs the browser grant.
