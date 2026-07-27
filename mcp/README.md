# antragsplattform MCP server

An [MCP](https://modelcontextprotocol.io) server that lets agents act on the
antragsplattform through its HTTP API. Authentication uses a standard OAuth2
Authorization-Code + PKCE **browser grant**. On the first tool call the server opens the
platform login in your browser. It captures the result on a loopback redirect and
exchanges it for a scoped bearer token. The server caches the token locally and refreshes
it automatically.

The agent acts **as the logged-in user**. The platform still authorizes every action with
the RBAC permissions of that user, intersected with the granted OAuth scope.

## Setup

This server needs Python ≥ 3.11. Install it (editable) from this directory:

```bash
pip install -e .
```

Configure it in your MCP client. Set the platform URL with `ANTRAGSPLATTFORM_URL`:

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
- `ANTRAGSPLATTFORM_SCOPE` (optional) — space-separated OAuth scopes. The default is the
  full curated set (`read applications:write votes:write budget:write meetings:write`).
  Narrow it to limit what the agent can do.

The platform must have OIDC configured. It must also register the public client id of
this server (`antragsplattform-mcp`, set with `OAUTH_MCP_CLIENT_ID`). The platform accepts
loopback redirect URIs (`http://127.0.0.1:<port>/callback`) automatically for native
clients.

## Scopes → permissions

| Scope | Grants (capped by the user's own rights) |
|-------|------------------------------------------|
| `read` | read applications, budgets, votes, meetings, audit, exports |
| `applications:write` | create / comment / transition applications |
| `votes:write` | create / open / close / cancel / manage votes (NEVER cast a ballot — only a human may do that. `vote.cast` is in `FORBIDDEN_PERMISSIONS` and is never grantable) |
| `budget:write` | book expenses, manage accounts, invoices & FinTS bank reconciliation |
| `meetings:write` | manage meetings & agendas |

## Tools

Auth: `login`, `whoami`, `logout`.
Applications: `list_applications`, `get_application`, `get_application_timeline`,
`create_application`, `comment_application`.
Flow: `list_transitions`, `fire_transition`.
Votes: `get_vote`, `create_application_vote`, `open_vote`, `close_vote`, `cancel_vote`,
`create_meeting_vote`, `delete_meeting_vote`. There is no `cast_ballot` tool, because only
a human may cast a ballot.
Budget: `list_budgets`, `get_budget_applications`, `book_expense`, `list_expenses`,
accounts (`list_accounts`/`list_account_options`/`create_account`/`update_account`,
including the FinTS endpoint and the BLZ).
Invoices: `list_invoices`, `get_invoice`, `create_invoice`, `update_invoice`,
`delete_invoice`, `parse_invoice` (ZUGFeRD/Factur-X PDF → fields + fileToken),
`upload_invoice_file`.
Bank reconcile (#fints): `get_/set_/delete_fints_credential`, `fints_sync`,
`fints_submit_tan`, `import_statement_file` (CAMT.053/MT940), `list_statement_lines`,
`get_statement_line`, `confirm_statement_line`, `ignore_statement_line`,
`reactivate_statement_line`. `fints_sync` can return `needs_tan`, and then a human approves
the TAN. `get_statement_line` also returns `rawPayload` for import diagnostics.
`ignore_statement_line` takes an optional audit reason.
Meetings: `list_meetings`, `get_meeting`.

## Token cache

Tokens live at `~/.config/antragsplattform-mcp/token-<hash>.json` (mode 600), one file per
platform URL. `logout` deletes the file. The next call runs the browser grant again.
