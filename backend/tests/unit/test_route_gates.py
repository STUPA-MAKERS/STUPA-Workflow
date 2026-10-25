"""Every authenticated route names a permission in its gate or is on an explicit list.

The rule of the RBAC checks:

- A global permission goes into the route gate: ``require_principal("perm", ...)``,
  ``require_any_permission(...)``, ``require_group(...)`` or ``require_applicant()``.
- A gremium permission goes through ``app.modules.auth.policy``.
- An object rule (the owner, the gremium of the object, the minute-taker of the
  meeting) has an authenticated gate only, and the route is on
  ``OBJECT_CHECK_ROUTES``. The value names the policy function that authorizes the
  route. Review this list and the check of each entry on every change to it.

The test reuses the walk of ``test_public_routes``. An authenticated route is a
route with an auth dependency (see ``_is_auth`` there). The test fails for an
authenticated route that names no permission and is not on the list, and for a
stale entry of the list.

Groups of ``OBJECT_CHECK_ROUTES`` that authorize no object:

- Self: the route reads or writes only the data of the caller (``/auth/me``, the
  own grants, preferences, calendar feed and avatar, the OAuth consent).
- Master data: ``GET /api/gremien`` serves id, name and variant to any member, and
  the avatar of a principal is the same Gravatar image that the person list shows.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Final

from app.deps import require_any_permission, require_applicant, require_group, require_principal
from tests.unit.test_public_routes import _is_auth, _routes

_LIVE = "MeetingService.assert_can_read"
_MEETING_WRITE = "MeetingOut.can_write (PermissionOps.can_write)"
_MEETING_MANAGE = "PermissionOps.can_manage (policy.has_gremium_permission session.manage)"
_MEETING_VOTES = "MeetingOut.can_manage_votes (PermissionOps.can_manage_votes)"
_RUN_VOTE = "VotingService.assert_can_run_vote"
_MANAGE_VOTE = "VotingService.assert_can_manage_vote"
_TODO_READ = "BoardAccess.can_read"
_TODO_WRITE = "BoardAccess.can_write"
_TODO_CONFIGURE = "BoardAccess.can_configure"
_TODO_SCOPE = "BoardAccess.scope"
_REPORTER = "TicketService._reporter_ticket (own ticket)"
_REPORTER_NOTE = "TicketService._reporter_note (own ticket, own note)"
_GREMIUM_VIEW = "gremien.access.require_gremium (policy.can_view_gremium)"
_DELEGATION_VIEW = "DelegationService._assert_can_view_gremium"
_POOL_MANAGE = "DelegationService._require_pool_manage"
_PROTOCOL_WRITE = "ProtocolService.authorize_write"
_PROTOCOL_READ = "ProtocolService.authorize_read"
_BUDGET_NODE = "budget.tree_router._require_node_view"
_SELF = "self: the data of the caller only"

OBJECT_CHECK_ROUTES: Final[dict[tuple[str, str], str]] = {
    ("POST", "/api/admin/config-revisions/{revision_id}/restore"): (
        "config_revision.router._require_restore_perm (permission of the entity type)"
    ),
    ("GET", "/api/applications"): "applications.access.principal_reads_all + read_scope_for",
    ("GET", "/api/applications/tasks"): "ApplicationService.list_tasks (read_scope_for)",
    ("POST", "/api/applications/{application_id}/votes"): (
        "VotingService.assert_can_manage_group (manages_votes_in_gremium)"
    ),
    ("GET", "/api/auth/me"): _SELF,
    ("GET", "/api/budgets"): "budget.tree_router._has_full_view + member gremien",
    ("GET", "/api/budgets/{budget_id}/applications"): _BUDGET_NODE,
    ("GET", "/api/budgets/{budget_id}/expenses"): _BUDGET_NODE,
    ("GET", "/api/budgets/{budget_id}/fiscal-years"): _BUDGET_NODE,
    ("GET", "/api/calendar/me"): _SELF,
    ("POST", "/api/calendar/me/rotate"): _SELF,
    ("GET", "/api/delegations"): "DelegationService.list (own delegations, _can_manage)",
    ("POST", "/api/delegations"): "DelegationService.create (_independently_eligible, lead)",
    ("DELETE", "/api/delegations/{delegation_id}"): (
        "DelegationService.revoke (delegator or live lead)"
    ),
    ("GET", "/api/delegations/meetings/{meeting_id}/context"): _DELEGATION_VIEW,
    ("GET", "/api/delegations/meetings/{meeting_id}/recipients"): _DELEGATION_VIEW,
    ("GET", "/api/delegations/substitutes"): _DELEGATION_VIEW,
    ("POST", "/api/delegations/substitutes"): _POOL_MANAGE,
    ("DELETE", "/api/delegations/substitutes/{substitute_id}"): _POOL_MANAGE,
    ("GET", "/api/delegations/votes/{vote_id}/status"): (
        "DelegationService.vote_status (own delegations only)"
    ),
    ("GET", "/api/gremien"): "master data: id, name and variant of every gremium",
    ("GET", "/api/gremien/overview"): "GremienService.overview (policy.GREMIUM_VIEW_ALL)",
    ("GET", "/api/gremien/{gremium_id}/attendance"): _GREMIUM_VIEW,
    ("GET", "/api/gremien/{gremium_id}/attendance/{principal_id}"): _GREMIUM_VIEW,
    ("GET", "/api/gremien/{gremium_id}/decisions"): _GREMIUM_VIEW,
    ("GET", "/api/gremien/{gremium_id}/logo"): "policy.can_view_gremium",
    ("GET", "/api/gremien/{gremium_id}/meeting-defaults"): _MEETING_MANAGE,
    ("GET", "/api/gremien/{gremium_id}/meeting-members"): _MEETING_MANAGE,
    ("GET", "/api/gremien/{gremium_id}/meetings"): _GREMIUM_VIEW,
    ("GET", "/api/gremien/{gremium_id}/members"): _GREMIUM_VIEW,
    ("GET", "/api/meetings"): "PermissionOps._visible_gremium_ids",
    ("POST", "/api/meetings"): _MEETING_MANAGE,
    ("GET", "/api/meetings/gremien"): "PermissionOps._visible_gremium_ids",
    ("GET", "/api/meetings/timeline"): "PermissionOps._visible_gremium_ids",
    ("GET", "/api/meetings/{meeting_id}"): _LIVE,
    ("PATCH", "/api/meetings/{meeting_id}"): (
        "MeetingService.patch (can_manage, can_write, can_set_current_item, can_mark_done)"
    ),
    ("DELETE", "/api/meetings/{meeting_id}"): _MEETING_MANAGE,
    ("GET", "/api/meetings/{meeting_id}/agenda"): _LIVE,
    ("POST", "/api/meetings/{meeting_id}/agenda"): _MEETING_WRITE,
    ("GET", "/api/meetings/{meeting_id}/agenda/assignable"): _LIVE,
    ("PUT", "/api/meetings/{meeting_id}/agenda/order"): _MEETING_WRITE,
    ("PATCH", "/api/meetings/{meeting_id}/agenda/{item_id}"): _MEETING_WRITE,
    ("DELETE", "/api/meetings/{meeting_id}/agenda/{item_id}"): _MEETING_WRITE,
    ("PUT", "/api/meetings/{meeting_id}/agenda/{item_id}/done"): _MEETING_WRITE,
    ("GET", "/api/meetings/{meeting_id}/attendance"): _LIVE,
    ("PUT", "/api/meetings/{meeting_id}/attendance/me"): "AttendanceService.set_self (own row)",
    ("PUT", "/api/meetings/{meeting_id}/attendance/{principal_id}"): (
        "livevote.router._require_lead (PermissionOps.can_write)"
    ),
    ("DELETE", "/api/meetings/{meeting_id}/attendance/{principal_id}"): (
        "livevote.router._require_lead (PermissionOps.can_write)"
    ),
    ("GET", "/api/meetings/{meeting_id}/guests"): _MEETING_MANAGE,
    ("POST", "/api/meetings/{meeting_id}/guests/admit-all"): _MEETING_MANAGE,
    ("POST", "/api/meetings/{meeting_id}/guests/{guest_id}/admit"): _MEETING_MANAGE,
    ("POST", "/api/meetings/{meeting_id}/guests/{guest_id}/reject"): _MEETING_MANAGE,
    ("POST", "/api/meetings/{meeting_id}/guests/{guest_id}/remove"): _MEETING_MANAGE,
    ("POST", "/api/meetings/{meeting_id}/guests/{guest_id}/rename"): _MEETING_MANAGE,
    ("GET", "/api/meetings/{meeting_id}/join-link"): _MEETING_MANAGE,
    ("POST", "/api/meetings/{meeting_id}/join-code/rotate"): _MEETING_MANAGE,
    ("GET", "/api/meetings/{meeting_id}/protocol"): "ProtocolService.authorize_read_meeting",
    ("POST", "/api/meetings/{meeting_id}/protocol"): "ProtocolService.authorize_write_meeting",
    ("POST", "/api/meetings/{meeting_id}/protokollant-handover"): "HandoverOps.can_hand_over",
    ("DELETE", "/api/meetings/{meeting_id}/protokollant-handover"): "HandoverOps.can_hand_over",
    ("POST", "/api/meetings/{meeting_id}/votes"): (
        f"{_MEETING_VOTES} + PermissionOps.assert_can_run_votes"
    ),
    ("POST", "/api/meetings/{meeting_id}/votes/{vote_id}/open"): (
        f"{_MEETING_VOTES} + PermissionOps.assert_can_run_votes"
    ),
    ("DELETE", "/api/meetings/{meeting_id}/votes/{vote_id}"): _MEETING_VOTES,
    ("GET", "/api/notifications/preferences"): _SELF,
    ("PUT", "/api/notifications/preferences"): _SELF,
    ("GET", "/api/oauth/consent-request"): _SELF,
    ("POST", "/api/oauth/consent"): "self: oauth_router.consent (mcp.use after the deny path)",
    ("GET", "/api/oauth/finish"): _SELF,
    ("GET", "/api/oauth/grants"): _SELF,
    ("DELETE", "/api/oauth/grants"): _SELF,
    ("DELETE", "/api/oauth/grants/{grant_id}"): "oauth_router.revoke_grant (own grant)",
    ("GET", "/api/principals/me/avatar"): _SELF,
    ("GET", "/api/principals/{principal_id}/avatar"): "master data: the Gravatar of a person",
    ("PATCH", "/api/protocols/{protocol_id}"): (
        "ProtocolService.authorize_write + ProtocolService.authorize_finalize"
    ),
    ("DELETE", "/api/protocols/{protocol_id}"): _PROTOCOL_WRITE,
    ("POST", "/api/protocols/{protocol_id}/finalize"): "ProtocolService.authorize_finalize",
    ("GET", "/api/protocols/{protocol_id}/pdf"): _PROTOCOL_READ,
    ("GET", "/api/protocols/{protocol_id}/pdf/public"): _PROTOCOL_READ,
    ("POST", "/api/protocols/{protocol_id}/votes"): _PROTOCOL_WRITE,
    ("GET", "/api/tickets/mine"): "TicketService.reporter_list (own tickets)",
    ("GET", "/api/tickets/mine/{ticket_id}"): _REPORTER,
    ("POST", "/api/tickets/mine/{ticket_id}/notes"): _REPORTER,
    ("PATCH", "/api/tickets/mine/{ticket_id}/notes/{note_id}"): _REPORTER_NOTE,
    ("DELETE", "/api/tickets/mine/{ticket_id}/notes/{note_id}"): _REPORTER_NOTE,
    ("GET", "/api/todos/all/boards"): _TODO_SCOPE,
    ("GET", "/api/todos/boards"): _TODO_SCOPE,
    ("GET", "/api/todos/boards/{board_id}"): _TODO_READ,
    ("PATCH", "/api/todos/boards/{board_id}"): _TODO_CONFIGURE,
    ("GET", "/api/todos/boards/{board_id}/archive"): _TODO_READ,
    ("POST", "/api/todos/boards/{board_id}/columns"): _TODO_CONFIGURE,
    ("PUT", "/api/todos/boards/{board_id}/columns/order"): _TODO_CONFIGURE,
    ("PATCH", "/api/todos/boards/{board_id}/columns/{column_id}"): _TODO_CONFIGURE,
    ("DELETE", "/api/todos/boards/{board_id}/columns/{column_id}"): _TODO_CONFIGURE,
    ("POST", "/api/todos/boards/{board_id}/labels"): _TODO_CONFIGURE,
    ("PATCH", "/api/todos/boards/{board_id}/labels/{label_id}"): _TODO_CONFIGURE,
    ("DELETE", "/api/todos/boards/{board_id}/labels/{label_id}"): _TODO_CONFIGURE,
    ("GET", "/api/todos/boards/{board_id}/members"): _TODO_READ,
    ("GET", "/api/todos/cards"): _TODO_READ,
    ("POST", "/api/todos/cards"): _TODO_WRITE,
    ("GET", "/api/todos/cards/{card_id}"): _TODO_READ,
    ("PATCH", "/api/todos/cards/{card_id}"): _TODO_WRITE,
    ("DELETE", "/api/todos/cards/{card_id}"): _TODO_WRITE,
    ("POST", "/api/todos/cards/{card_id}/assignees"): _TODO_WRITE,
    ("DELETE", "/api/todos/cards/{card_id}/assignees/{principal_id}"): _TODO_WRITE,
    ("POST", "/api/todos/cards/{card_id}/checklist"): _TODO_WRITE,
    ("PATCH", "/api/todos/cards/{card_id}/checklist/{item_id}"): _TODO_WRITE,
    ("DELETE", "/api/todos/cards/{card_id}/checklist/{item_id}"): _TODO_WRITE,
    ("POST", "/api/todos/cards/{card_id}/comments"): _TODO_WRITE,
    ("PATCH", "/api/todos/cards/{card_id}/comments/{comment_id}"): _TODO_WRITE,
    ("DELETE", "/api/todos/cards/{card_id}/comments/{comment_id}"): _TODO_WRITE,
    ("POST", "/api/todos/cards/{card_id}/labels"): _TODO_WRITE,
    ("DELETE", "/api/todos/cards/{card_id}/labels/{label_id}"): _TODO_WRITE,
    ("POST", "/api/todos/cards/{card_id}/links"): _TODO_WRITE,
    ("DELETE", "/api/todos/cards/{card_id}/links/{link_id}"): _TODO_WRITE,
    ("POST", "/api/todos/cards/{card_id}/move"): _TODO_WRITE,
    ("POST", "/api/todos/cards/{card_id}/restore"): _TODO_WRITE,
    ("GET", "/api/todos/cards/{card_id}/tile"): _TODO_READ,
    ("POST", "/api/todos/cards/{card_id}/transfer"): _TODO_WRITE,
    ("GET", "/api/todos/link-targets"): "todos.access.token_reads + TodoLinks.search",
    ("GET", "/api/todos/linked"): "TodoService.linked (per-kind read checks)",
    ("GET", "/api/todos/mine"): _TODO_SCOPE,
    ("GET", "/api/todos/mine/boards"): _TODO_SCOPE,
    ("GET", "/api/votes"): "voting.listing.read_scope",
    ("POST", "/api/votes"): "PollService.can_create (policy.has_gremium_permission vote.manage)",
    ("GET", "/api/votes/{vote_id}"): "VotingService.assert_can_read",
    ("PATCH", "/api/votes/{vote_id}"): _MANAGE_VOTE,
    ("DELETE", "/api/votes/{vote_id}"): _MANAGE_VOTE,
    ("POST", "/api/votes/{vote_id}/ballot"): "VotingService.cast (roster of the vote)",
    ("POST", "/api/votes/{vote_id}/cancel"): _RUN_VOTE,
    ("POST", "/api/votes/{vote_id}/close"): _RUN_VOTE,
    ("POST", "/api/votes/{vote_id}/draw-lot"): _MANAGE_VOTE,
    ("POST", "/api/votes/{vote_id}/open"): _RUN_VOTE,
    ("POST", "/api/votes/{vote_id}/runoff"): _MANAGE_VOTE,
    ("WS", "/api/ws/meetings/{meeting_id}"): "livevote.router._authorize (is_participant)",
    ("WS", "/api/ws/meetings/{meeting_id}/beamer"): "livevote.router._authorize (is_participant)",
    ("WS", "/api/ws/todos"): "TodoLiveConnection (BoardAccess.can_read per board)",
}

_PERMISSION_FACTORIES: Final[tuple[Callable[..., Any], ...]] = (
    require_principal,
    require_any_permission,
)
_NAMED_FACTORIES: Final[tuple[Callable[..., Any], ...]] = (require_group, require_applicant)


def _closure_of(call: Callable[..., Any], factories: tuple[Callable[..., Any], ...]) -> bool:
    qualname = getattr(call, "__qualname__", "")
    return any(qualname.startswith(f"{f.__qualname__}.<locals>.") for f in factories)


def _names_permission(call: Callable[..., Any]) -> bool:
    """Tell if an auth closure names a permission, a group or the applicant scope."""
    if _closure_of(call, _NAMED_FACTORIES):
        return True
    if _closure_of(call, _PERMISSION_FACTORIES):
        return bool(inspect.getclosurevars(call).nonlocals.get("perms"))
    return False


def _unnamed() -> set[tuple[str, str]]:
    """Return the authenticated routes whose gate names no permission."""
    out: set[tuple[str, str]] = set()
    for method, path, calls in _routes():
        gates = [call for call in calls if _is_auth(call)]
        if gates and not any(_names_permission(call) for call in gates):
            out.add((method, path))
    return out


def test_every_route_without_a_named_permission_is_listed() -> None:
    unnamed = _unnamed()
    listed = set(OBJECT_CHECK_ROUTES)
    assert sorted(unnamed - listed) == [], "a route has a bare gate and is not listed"
    assert sorted(listed - unnamed) == [], "a list entry is gone or now names a permission"


def test_every_entry_names_its_policy() -> None:
    assert all(rule.strip() for rule in OBJECT_CHECK_ROUTES.values())


def test_names_permission_reads_the_closure() -> None:
    assert _names_permission(require_principal("x"))
    assert not _names_permission(require_principal())
    assert _names_permission(require_any_permission("x", "y"))
    assert not _names_permission(require_any_permission())
    assert _names_permission(require_group("g"))
    assert _names_permission(require_applicant())
    assert not _names_permission(_unnamed)
