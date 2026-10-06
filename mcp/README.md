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
  full curated set (`read applications:write votes:write budget:write meetings:write
  forms:write flows:write admin:write`). Narrow it to limit what the agent can do.

The platform must have OIDC configured. It must also register the public client id of
this server (`antragsplattform-mcp`, set with `OAUTH_MCP_CLIENT_ID`). The platform accepts
loopback redirect URIs (`http://127.0.0.1:<port>/callback`) automatically for native
clients.

## Scopes → permissions

| Scope | Grants (capped by the user's own rights) |
|-------|------------------------------------------|
| `read` | read applications, budgets, votes, meetings (incl. `meeting.view_all`), audit, exports |
| `applications:write` | comment / transition / manage applications, capture an application on behalf of an applicant (`application.create_on_behalf`) |
| `votes:write` | create / open / close / cancel / manage votes through the gremium right `vote.manage` (NEVER cast a ballot — only a human may do that. `vote.cast` is in `FORBIDDEN_PERMISSIONS` and is never grantable) |
| `budget:write` | book expenses, manage cost centers & invoices |
| `meetings:write` | the gremium rights `session.manage` (meetings & agendas, and every vote of the gremium: the votes of its meetings and the application votes that no meeting holds), `protocol.write` (minutes) and `protocol.finalize` (finalize & send the minutes) |

The meeting and vote rights are gremium rights. No global permission grants them. The
scope does not grant them either. It only
lets them through when your role in the meeting's gremium holds them (or you are admin).
A token without `meetings:write` cannot manage a meeting or write minutes, whatever your
gremium role says.

The meeting lead includes the votes of the meeting. A `meetings:write` token of a holder of
`session.manage` can thus create, open, close and cancel the votes of that gremium's
meetings, the votes of its applications that no meeting holds, and change the current
agenda item, also without `votes:write`. `votes:write` lets `vote.manage` through for all
other people who manage votes: the minute-taker and a gremium role with `vote.manage`
only. A vote names the gremium UUID as `eligibleGroup`.

## Tools

Auth: `login`, `whoami`, `logout`.
Applications: `list_applications`, `get_application`, `get_application_timeline`,
`create_application`, `comment_application`.
Flow: `list_transitions`, `fire_transition`.
Votes: `get_vote`, `create_application_vote`, `open_vote`, `close_vote`, `cancel_vote`,
`create_meeting_vote`, `delete_meeting_vote`. There is no `cast_ballot` tool, because only
a human may cast a ballot.
Budget: `list_budgets`, `get_budget_applications`, `book_expense`, `list_expenses`.
Invoices: `list_invoices`, `get_invoice`, `create_invoice`, `update_invoice`,
`delete_invoice`, `parse_invoice` (ZUGFeRD/Factur-X PDF → fields + fileToken),
`upload_invoice_file`.
Meetings: `list_meetings`, `get_meeting`, `create_meeting`, `update_meeting`, `delete_meeting`,
the agenda tools, attendance (`get_attendance`, `set_attendance`, `reset_attendance`) and the
minute-taker handover (`protokollant_handover`, `cancel_protokollant_handover`).
Public meeting (#17): `list_meeting_guests`, `admit_meeting_guest`, `admit_all_meeting_guests`,
`reject_meeting_guest`, `remove_meeting_guest`, `rename_meeting_guest`,
`get_meeting_join_link`, `rotate_meeting_join_code`. No tool casts a ballot for a guest.
On behalf (#11): `create_application_on_behalf`, `search_on_behalf_applicants` (needs
`application.create_on_behalf`).
Audit: `list_audit`, `verify_audit_chain` (live), `get_latest_audit_verification` (stored).

The list above is not complete. The server has about 160 tools in the modules of
`antragsplattform_mcp/tools/`, also for flow and form editing, protocols, delegations,
budget structure and the admin pages. `.claude/skills/mcp/SKILL.md` maps each tool group to
its backend route.

## Token cache

Tokens live at `~/.config/antragsplattform-mcp/token-<hash>.json` (mode 600), one file per
platform URL. `logout` deletes the file. The next call runs the browser grant again.
