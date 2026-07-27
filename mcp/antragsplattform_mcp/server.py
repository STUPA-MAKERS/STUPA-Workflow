"""FastMCP server that exposes platform API actions as tools.

Auth is transparent. See `client` and `auth`. The first tool call starts a browser login
with OAuth2 and PKCE. The server caches the token and refreshes it automatically. The
platform caps every right server-side, at the permissions of the user intersected with
the granted scope. One thing is forbidden by design. There is no `cast_ballot` tool and
no token ever gets `vote.cast`. An agent manages votes but never votes.

The tool definitions live in `tools`, one module per domain group. The `schemas` module
types the request bodies as a camelCase wire mirror of the backend.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools import register_all
from .tools._common import cfg

_INSTRUCTIONS = """\
antragsplattform — act on a student-government application/budget/meeting platform via its API.

AUTH: the first tool call opens a browser login (OAuth2 + PKCE) and caches a token; it
refreshes automatically. If a call returns an auth error, call `login` to re-authenticate.
`whoami` shows your identity, roles, permissions and committees (gremien). Everything you do
is authorized server-side by YOUR permissions ∩ the granted scope — a tool may return 403
if your account lacks the permission; that is expected, not a bug.

HARD RULE: you can create/open/close/manage votes, but you can NEVER cast a ballot — there is
no such tool and the server refuses it. Voting is reserved for humans.

TYPICAL FLOWS:
- Decide on an application: `list_applications` → `get_application` → `list_transitions`
  (shows the firable transition ids) → `fire_transition(application_id, transition_id, note)`.
  `list_tasks` shows the applications the logged-in user can currently act on.
- Create an application: `list_application_types` → `get_effective_form(type_id)` →
  `create_application(type_id, data={...})` with the form-field values.
- Edit the flow: prefer the ATOMIC ops — `flow_add_state`, `flow_update_state`,
  `flow_remove_state`, `flow_add_transition`, `flow_update_transition(index, …)`,
  `flow_remove_transition(index)`, `flow_set_positions`, `flow_set_group`,
  `flow_delete_group`. Transition indices are positions in the `transitions` array as
  returned by `get_global_flow` — read first, then patch by index. Each op re-reads the
  current flow, applies the change and activates a new version. Use `set_global_flow`
  only for full rebuilds.
- Edit a form: same pattern — `get_latest_form_version(type_id)` then `form_add_field`,
  `form_update_field`, `form_remove_field`, `form_move_field`. Each op creates + activates
  a new form version. `create_form_version` replaces the whole field list.
- Run a meeting: `create_meeting` → `add_agenda_item` → `create_meeting_vote` → `close_vote`.
- Minutes (Protokoll): `get_or_create_protocol(meeting_id)` → `update_protocol(markdown)` →
  `finalize_protocol`. Finalize is ASYNC: re-fetch until `status` is `final`, a fall back to
  `draft` means the render failed.
- Budget: `list_budgets` (tree), `update_budget`, `book_expense`, `set_allocation`,
  `create_budget_transfer`; bind an application via `assign_application_budget`. Browse all
  bookings flat/filtered with `list_expenses`.
- Invoices (#invoices): `list_invoices`/`get_invoice`/`create_invoice`/`update_invoice`/
  `delete_invoice`. To attach an original PDF: `parse_invoice(file_path)` (ZUGFeRD/Factur-X →
  extracted fields + `fileToken`) or `upload_invoice_file(file_path)`, then pass `fileToken`
  to `create_invoice`.
- Bank reconcile (#fints): the admin sets a Konto's FinTS connection (endpoint+BLZ) via
  `update_account`; each booker stores their personal login with
  `set_fints_credential(account_id, {fintsLogin, fintsPin})`. Then either
  `import_statement_file(account_id, file_path)` (CAMT.053/MT940 — no bank/TAN) OR
  `fints_sync(account_id)` (live). `fints_sync` may return `status='needs_tan'` (sessionToken +
  challenge) — PSD2/SCA needs a HUMAN to approve/enter the TAN; relay it, then
  `fints_submit_tan(account_id, session_token, tan)` (empty tan = decoupled pushTAN poll). A 409
  means the bank locked the access — do NOT retry. Review staged rows with
  `list_statement_lines` → book each via `confirm_statement_line(line_id, {budgetId})` (or
  `{matchExpenseId}` to attach to an existing booking) or drop it with `ignore_statement_line`.

SCHEMAS: tool parameters are typed and mirror the API (camelCase keys). For guard/action
shapes and form-field types call `get_config_schemas` (authoritative JSON-Schemas).
Money amounts are decimal strings ("1500.00"). Ids are UUID strings. Prefer reading
(get/list) before writing, and echo back what you changed.
"""

mcp = FastMCP("antragsplattform", instructions=_INSTRUCTIONS)
register_all(mcp)


def main() -> None:
    """Console entry point (stdio transport)."""
    cfg()  # fail fast if ANTRAGSPLATTFORM_URL is missing
    mcp.run()


if __name__ == "__main__":
    main()
