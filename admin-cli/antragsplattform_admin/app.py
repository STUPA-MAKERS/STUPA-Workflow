"""The orchestrator that owns the DB connection and wires the UI together.

`AdminCLI` drives the slash-commands for users, roles, OIDC mappings and the audit
log. It also holds the inline selector. It satisfies three protocols.
`protocols.CompleterHost` serves the completer. `AppContext` serves the log and the
form components. `AppView` serves the layout and the key bindings.

The log model and its rendering live in `log_panel.LogPanel`. The domain-row
formatting lives in `views`. The form dialog lives in `form.FormController`. This
module coordinates them.

DB writes bypass the API. They write no audit entry and apply no RBAC guard. Rows
carry `granted_by = 'admin-cli'`. Every mutation asks for confirmation.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType

from . import __version__, layout, ops, views
from .commands import (
    AUDIT_KEYS,
    BASE_COMMANDS,
    HELP_LINES,
    MAPPING_ACTIONS,
    ROLE_ACTIONS,
    USER_ACTIONS,
)
from .completion import CommandCompleter
from .config import Config, resolve
from .db import Db, DbError, connect_auto
from .form import FormController
from .log_panel import LogPanel
from .models import Choices, Form, FormField, LogEntry, Selector
from .panels import selector_fragments as render_selector
from .permissions import FORBIDDEN_PERMISSIONS, PERMISSION_CATALOGUE
from .protocols import Handler, MouseHandler

# Options shown at once in the inline selector. This matches the selector panel height.
_SELECTOR_ROWS = 12
# Audit entries fetched per page (/audit and each /more).
_AUDIT_PAGE = 50


class AdminCLI:
    """Drives the admin console from a full-screen prompt_toolkit UI."""

    def __init__(self, cfg: Config, db: Db | None, startup_notes: list[str]) -> None:
        self.cfg = cfg
        self.db = db
        self._startup_notes = startup_notes
        self._selector: Selector | None = None
        self._counts: dict[str, Any] = {}
        self._users_cache: list[dict[str, Any]] = []
        self._roles_cache: list[dict[str, Any]] = []
        self._mappings_cache: list[dict[str, Any]] = []
        # Audit paging state: the active filters, the oldest id already shown and the
        # last rendered date. The date keeps /more from repeating the day heading.
        self._audit_filters: dict[str, str] = {}
        self._audit_oldest: int | None = None
        self._audit_last_date = ""

        self._buffer = Buffer(
            completer=CommandCompleter(self),
            complete_while_typing=True,
            multiline=False,
            history=InMemoryHistory(),
            accept_handler=self._accept,
        )
        self._log_panel = LogPanel(self)
        self._form = FormController(self)
        self._app: Application = layout.build_app(self)

    # The AppContext protocol.
    @property
    def buffer(self) -> Buffer:
        return self._buffer

    def info(self, text: str) -> None:
        """Append an informational line to the log."""
        self._log_panel.append(LogEntry(fragments=[("class:info", f"· {text}\n")]))

    def error(self, text: str) -> None:
        """Append an error line to the log."""
        self._log_panel.append(LogEntry(fragments=[("class:error", f"✗ {text}\n")]))

    def warn(self, text: str) -> None:
        """Append a warning line to the log."""
        self._log_panel.append(LogEntry(fragments=[("class:warn", f"⚠ {text}\n")]))

    def invalidate(self) -> None:
        """Request a repaint via the concrete app."""
        self._app.invalidate()

    # The AppView protocol.
    @property
    def logs(self) -> LogPanel:
        """The log panel as rendered by the layout."""
        return self._log_panel

    @property
    def form_panel(self) -> FormController:
        """The form dialog panel as driven by the key bindings."""
        return self._form

    def open_form(self, form: Form) -> None:
        """Open `form` in the shared form dialog."""
        self._form.open(form)

    def line_prefix(self, line_number: int, wrap_count: int) -> StyleAndTextTuples:
        if line_number == 0 and wrap_count == 0:
            return [("class:prompt", "› ")]
        return [("class:cont", "… ")]

    def scroll_button_fragments(self) -> StyleAndTextTuples:
        return [
            (
                "class:scroll-btn",
                " ↓ latest ",
                self._click(self._log_panel.scroll_to_bottom),
            )
        ]

    def toolbar(self) -> StyleAndTextTuples:
        connected = self.db is not None
        status: tuple[str, str, MouseHandler] = (
            ("class:on", f"● {self.db.label}  ", self._click(lambda: self._cmd_status([])))
            if self.db is not None
            else ("class:off", "○ disconnected  ", self._click(lambda: self._cmd_connect([])))
        )
        fragments: StyleAndTextTuples = [status]
        if connected and self._counts:
            for key, label, command in (
                ("users", "users", "/users"),
                ("roles", "roles", "/roles"),
                ("mappings", "maps", "/mappings"),
            ):
                count = views.fmt(self._counts.get(key))
                fragments.append(("class:bottom-toolbar", "·  "))
                fragments.append(
                    (
                        "class:bottom-toolbar",
                        f"{label}:{count}  ",
                        self._click(lambda cmd=command: self._handle_line(cmd)),
                    )
                )
            head = views.fmt(self._counts.get("audit_head"))
            fragments.append(("class:bottom-toolbar", "·  "))
            fragments.append(
                (
                    "class:bottom-toolbar",
                    f"audit:#{head}  ",
                    self._click(lambda: self._handle_line("/audit")),
                )
            )
        if self.cfg.read_only:
            fragments.append(("class:bottom-toolbar", "·  "))
            fragments.append(("class:ro", "read-only  "))
        elif connected:
            fragments.append(("class:bottom-toolbar", "·  "))
            fragments.append(("class:ro", "⚠ direct db  "))
        fragments.append(("class:bottom-toolbar", "·  "))
        fragments.append(
            ("class:bottom-toolbar", "/help", self._click(lambda: self._cmd_help([])))
        )
        return fragments

    def _click(self, action: Callable[[], None]) -> MouseHandler:
        def handler(mouse_event: MouseEvent) -> object:
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                self._log_panel.close_detail()
                self._guard(action)
                get_app().invalidate()
            elif mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self._log_panel.set_hover(None)
            else:
                return NotImplemented
            return None

        return handler

    def choose(
        self,
        title: str,
        values: Choices,
        on_choose: Callable[[str | None], None],
        *,
        searchable: bool = False,
    ) -> None:
        """Open an inline selector and call `on_choose` with the picked key or `None`."""
        if not values:
            self.error(f"{title.lower()}: nothing to select")
            self._guard(lambda: on_choose(None))
            return
        self._selector = Selector(
            title=title, values=values, on_choose=on_choose, searchable=searchable
        )
        self.invalidate()

    def confirm(self, question: str, on_yes: Callable[[], None]) -> None:
        """Ask an explicit yes or no through the selector. No is the default."""
        self.choose(
            question,
            [("no", "no — cancel"), ("yes", "yes — do it")],
            lambda key: on_yes() if key == "yes" else self.info("cancelled"),
        )

    def selector_fragments(self) -> StyleAndTextTuples:
        selector = self._selector
        if selector is None:
            return []
        count = len(selector.visible())
        # Keep the scroll window on the cursor. A long list then stays navigable
        # and does not overflow the panel.
        selector.cursor = min(selector.cursor, max(0, count - 1))
        if selector.cursor < selector.scroll:
            selector.scroll = selector.cursor
        elif selector.cursor >= selector.scroll + _SELECTOR_ROWS:
            selector.scroll = selector.cursor - _SELECTOR_ROWS + 1
        selector.scroll = max(0, min(selector.scroll, max(0, count - _SELECTOR_ROWS)))
        return render_selector(selector, self._selector_option, _SELECTOR_ROWS)

    def selector_title(self) -> str:
        return self._selector.title if self._selector else ""

    def showing_selector(self) -> bool:
        return self._selector is not None

    def selector_searchable(self) -> bool:
        return self._selector is not None and self._selector.searchable

    def selector_move(self, delta: int) -> None:
        if self._selector is not None:
            count = len(self._selector.visible())
            if count:
                self._selector.cursor = (self._selector.cursor + delta) % count
                self.invalidate()

    def selector_type(self, text: str) -> None:
        selector = self._selector
        if selector is None or not selector.searchable:
            return
        if len(text) == 1 and text.isprintable():
            selector.query += text
            selector.cursor = 0
            selector.scroll = 0
            self.invalidate()

    def selector_backspace(self) -> None:
        selector = self._selector
        if selector is None or not selector.searchable or not selector.query:
            return
        selector.query = selector.query[:-1]
        selector.cursor = 0
        selector.scroll = 0
        self.invalidate()

    def selector_pick_visible(self, position: int) -> None:
        if self._selector is not None:
            self.selector_pick(self._selector.scroll + position)

    def selector_pick(self, index: int | None = None) -> None:
        selector = self._selector
        if selector is None:
            return
        options = selector.visible()
        position = selector.cursor if index is None else index
        if position >= len(options):
            return
        chosen = options[position][0]
        self._selector = None
        self.invalidate()
        self._guard(lambda: selector.on_choose(chosen))

    def selector_cancel(self) -> None:
        selector = self._selector
        if selector is None:
            return
        self._selector = None
        self.invalidate()
        self._guard(lambda: selector.on_choose(None))

    def _selector_option(self, index: int) -> MouseHandler:
        def handler(mouse_event: MouseEvent) -> object:
            event_type = mouse_event.event_type
            if event_type == MouseEventType.MOUSE_UP:
                self.selector_pick(index)
            elif event_type == MouseEventType.MOUSE_MOVE:
                if self._selector is not None and self._selector.cursor != index:
                    self._selector.cursor = index
                    self.invalidate()
            elif event_type == MouseEventType.SCROLL_UP:
                self.selector_move(-1)
            elif event_type == MouseEventType.SCROLL_DOWN:
                self.selector_move(1)
            else:
                return NotImplemented
            return None

        return handler

    # The CompleterHost protocol.
    def command_names(self) -> list[str]:
        return list(BASE_COMMANDS)

    def argument_options(self, parts: list[str]) -> list[str]:
        command = parts[0]
        if command == "/user":
            if len(parts) == 2:
                # Single-token handles only: the email, else the sub. A display
                # name with spaces would not survive the whitespace-split parser.
                return [
                    handle
                    for r in self._users_cache
                    if (handle := views.fmt(r.get("email")) or views.fmt(r.get("sub")))
                    and " " not in handle
                ]
            if len(parts) == 3:
                return list(USER_ACTIONS)
        if command == "/role":
            if len(parts) == 2:
                return [views.fmt(r.get("key")) for r in self._roles_cache]
            if len(parts) == 3:
                return list(ROLE_ACTIONS)
        if command == "/mapping":
            if len(parts) == 2:
                return [views.fmt(r.get("oidc_group")) for r in self._mappings_cache]
            if len(parts) == 3:
                return list(MAPPING_ACTIONS)
        if command == "/audit":
            return list(AUDIT_KEYS)
        return []

    def _guard(self, action: Callable[[], object]) -> None:
        """Run `action` and show any exception in the log instead of a crash."""
        try:
            _ = action()
        except DbError as error:
            self.error(str(error))
        except Exception as error:  # noqa: BLE001 — a handler must never kill the UI
            self.error(f"{type(error).__name__}: {error}")

    def _accept(self, buffer: Buffer) -> bool:
        text = buffer.text.strip()
        if text:
            self._handle_line(text)
        return False

    def _handle_line(self, line: str) -> None:
        self._log_panel.append(LogEntry(fragments=[("class:prompt", f"› {line}\n")]))
        try:
            if not line.startswith("/"):
                self.error("commands start with / — try /help")
                return
            if not self._dispatch(line):
                get_app().exit()
        except DbError as error:
            self.error(str(error))
        except Exception as error:  # noqa: BLE001 — never let a command crash the UI
            self.error(f"{type(error).__name__}: {error}")

    def _dispatch(self, line: str) -> bool:
        name, *args = line.split()
        if name in ("/quit", "/exit"):
            return False
        handlers: dict[str, Handler] = {
            "/users": self._cmd_users,
            "/user": self._cmd_user,
            "/roles": self._cmd_roles,
            "/role": self._cmd_role,
            "/new-role": self._cmd_new_role,
            "/mappings": self._cmd_mappings,
            "/mapping": self._cmd_mapping,
            "/new-mapping": self._cmd_new_mapping,
            "/audit": self._cmd_audit,
            "/more": self._cmd_more,
            "/status": self._cmd_status,
            "/connect": self._cmd_connect,
            "/clear": lambda _args: self._log_panel.clear(),
            "/help": self._cmd_help,
        }
        handler = handlers.get(name)
        if handler is None:
            self.error(f"unknown command {name} — /help")
        else:
            handler(args)
        return True

    def _require_db(self) -> Db | None:
        if self.db is None:
            self.error("not connected — /connect first")
        return self.db

    def _writable(self) -> Db | None:
        if self.cfg.read_only:
            self.error("started with --read-only; writes are disabled")
            return None
        return self._require_db()

    def _run_write(self, do: Callable[[Db], int], success: str) -> None:
        db = self._writable()
        if db is None:
            return
        try:
            n = do(db)
        except DbError as exc:
            self.error(str(exc))
            return
        self.info(f"{success} ({n} row(s))")
        self._refresh_caches()

    def _refresh_caches(self) -> None:
        """Refresh the completion caches and toolbar counts (best-effort)."""
        db = self.db
        if db is None:
            return
        try:
            self._users_cache = ops.list_users(db)
            self._roles_cache = ops.list_roles(db)
            self._mappings_cache = ops.list_mappings(db)
            self._counts = ops.counts(db)
        except DbError as exc:
            self.error(f"cache refresh failed: {exc}")

    def _cmd_connect(self, _args: list[str]) -> None:
        fresh, notes = connect_auto(self.cfg)
        for note in notes:
            (self.info if fresh is not None else self.error)(note)
        if fresh is None:
            if self.db is not None:
                self.info("keeping the existing connection")
            return
        if self.db is not None:
            self.db.close()
        self.db = fresh
        self._refresh_caches()

    def _cmd_status(self, _args: list[str]) -> None:
        self.info(f"mode:        {self.db.label if self.db else 'disconnected'}")
        self.info(f"dsn:         {self.cfg.display_url}")
        self.info(f"compose:     {self.cfg.compose_file} (service {self.cfg.service})")
        self.info(f"read-only:   {self.cfg.read_only}")
        if self._counts:
            self.info(
                "entities:    "
                f"{views.fmt(self._counts.get('users'))} users · "
                f"{views.fmt(self._counts.get('roles'))} roles · "
                f"{views.fmt(self._counts.get('mappings'))} mappings · "
                f"audit head #{views.fmt(self._counts.get('audit_head'))}"
            )
        if not self.cfg.read_only and self.db is not None:
            self.warn("writes bypass the API: no audit entry, no RBAC guards")

    def _cmd_help(self, _args: list[str]) -> None:
        for line in HELP_LINES:
            self.info(line)

    def _cmd_users(self, args: list[str]) -> None:
        db = self._require_db()
        if db is None:
            return
        search = " ".join(args) if args else None
        rows = ops.list_users(db, search)
        self._users_cache = rows if not search else self._users_cache
        title = f"users ({len(rows)})" + (f" · “{search}”" if search else "")
        self._log_panel.append(LogEntry(fragments=views.separator(title)))
        if not rows:
            self.info("no matches")
        for row in views.user_rows(rows):
            self._log_panel.append_record(row)

    def _resolve_user(
        self, term: str | None, then: Callable[[dict[str, Any]], None]
    ) -> None:
        """Find one principal by `term`, or through a searchable selector."""
        db = self._require_db()
        if db is None:
            return
        rows = ops.list_users(db, term)
        if term and len(rows) == 1:
            # Substring match. Name the user it resolved to before the action runs.
            self.info(f"user → {views.user_name(rows[0])}")
            then(rows[0])
            return
        if term and not rows:
            self.error(f"no user matches {term!r}")
            return
        by_id = {views.fmt(r["id"]): r for r in rows}
        self.choose(
            "User",
            [
                (views.fmt(r["id"]), f"{'●' if views.truthy(r['active']) else '○'} "
                 f"{views.user_name(r)}  [{views.fmt(r.get('roles')) or '—'}]")
                for r in rows
            ],
            lambda key: then(by_id[key]) if key else None,
            searchable=True,
        )

    def _cmd_user(self, args: list[str]) -> None:
        # The last token is the action when it names one. Everything before it is
        # the search term. A display name can contain spaces.
        action: str | None = None
        if args and args[-1].lower() in USER_ACTIONS:
            action = args[-1].lower()
            args = args[:-1]
        term = " ".join(args) if args else None
        self._resolve_user(term, lambda row: self._user_action(row, action))

    def _user_action(self, row: dict[str, Any], action: str | None) -> None:
        if action is None:
            active = views.truthy(row.get("active"))
            options: Choices = [
                ("show", "show — full record"),
                ("roles", "roles — list assignments"),
                ("grant", "grant — add a role"),
                ("revoke", "revoke — remove an assignment"),
                (
                    "deactivate" if active else "activate",
                    "deactivate — disable login" if active else "activate — enable login",
                ),
                ("delete", "delete — remove the principal (cascades!)"),
            ]
            self.choose(
                views.user_name(row),
                options,
                lambda key: self._user_action(row, key) if key else None,
            )
            return
        dispatch: dict[str, Callable[[dict[str, Any]], None]] = {
            "show": self._user_show,
            "roles": self._user_roles,
            "grant": self._user_grant,
            "revoke": self._user_revoke,
            "activate": lambda r: self._user_set_active(r, True),
            "deactivate": lambda r: self._user_set_active(r, False),
            "delete": self._user_delete,
        }
        dispatch[action](row)

    def _assignment_labels(self, principal_id: str) -> tuple[Choices, int]:
        db = self._require_db()
        if db is None:
            return [], 0
        rows = ops.list_user_roles(db, principal_id)
        values: Choices = [
            (
                views.fmt(a["id"]),
                f"{views.fmt(a['role_key'])}"
                + (f" @ {views.fmt(a['gremium'])}" if a.get("gremium") else " (global)"),
            )
            for a in rows
        ]
        return values, len(rows)

    def _user_show(self, row: dict[str, Any]) -> None:
        values, _count = self._assignment_labels(views.fmt(row["id"]))
        # Replace the aggregated roles column with the precise per-scope list.
        assignments = ", ".join(label for _key, label in values)
        rendered = views.user_rows([{**row, "roles": assignments}])
        if rendered:
            self._log_panel.pop_out(rendered[0][1], rendered[0][2])

    def _user_roles(self, row: dict[str, Any]) -> None:
        values, count = self._assignment_labels(views.fmt(row["id"]))
        self.info(f"{views.user_name(row)} — {count} assignment(s)")
        for _key, label in values:
            self._log_panel.append(
                LogEntry(fragments=[("class:value", f"  {label}\n")])
            )

    def _user_grant(self, row: dict[str, Any]) -> None:
        db = self._writable()
        if db is None:
            return
        roles = ops.list_roles_simple(db)
        role_by_id = {views.fmt(r["id"]): r for r in roles}

        def picked_role(role_id: str | None) -> None:
            if not role_id:
                return
            gremien = ops.list_gremien(db)
            values: Choices = [("", "(global)")]
            values += [(views.fmt(g["id"]), views.fmt(g["name"])) for g in gremien]

            def picked_scope(gremium_id: str | None) -> None:
                if gremium_id is None:
                    return
                self._run_write(
                    lambda d: ops.grant_role(
                        d, views.fmt(row["id"]), role_id, gremium_id or None
                    ),
                    f"granted {views.fmt(role_by_id[role_id]['key'])} to {views.user_name(row)}",
                )

            self.choose("Scope", values, picked_scope)

        self.choose(
            "Role",
            [(views.fmt(r["id"]), views.fmt(r["key"])) for r in roles],
            picked_role,
            searchable=len(roles) > _SELECTOR_ROWS,
        )

    def _user_revoke(self, row: dict[str, Any]) -> None:
        if self._writable() is None:
            return
        values, _count = self._assignment_labels(views.fmt(row["id"]))

        def picked(assignment_id: str | None) -> None:
            if not assignment_id:
                return
            label = next(lbl for key, lbl in values if key == assignment_id)
            self.confirm(
                f"Revoke {label} from {views.user_name(row)}?",
                lambda: self._run_write(
                    lambda d: ops.revoke_assignment(d, assignment_id),
                    "assignment revoked",
                ),
            )

        self.choose("Revoke assignment", values, picked)

    def _user_set_active(self, row: dict[str, Any], active: bool) -> None:
        if self._writable() is None:
            return
        verb = "Activate" if active else "Deactivate"
        self.confirm(
            f"{verb} {views.user_name(row)}?",
            lambda: self._run_write(
                lambda d: ops.set_user_active(d, views.fmt(row["id"]), active),
                f"user {'activated' if active else 'deactivated'}",
            ),
        )

    def _user_delete(self, row: dict[str, Any]) -> None:
        if self._writable() is None:
            return
        self.confirm(
            f"DELETE principal {views.user_name(row)}? "
            "Cascades sessions + role assignments — irreversible.",
            lambda: self._run_write(
                lambda d: ops.delete_user(d, views.fmt(row["id"])), "user deleted"
            ),
        )

    def _cmd_roles(self, _args: list[str]) -> None:
        db = self._require_db()
        if db is None:
            return
        rows = ops.list_roles(db)
        self._roles_cache = rows
        self._log_panel.append(LogEntry(fragments=views.separator(f"roles ({len(rows)})")))
        for row in views.role_rows(rows):
            self._log_panel.append_record(row)

    def _resolve_role(
        self, term: str | None, then: Callable[[dict[str, Any]], None]
    ) -> None:
        db = self._require_db()
        if db is None:
            return
        rows = ops.list_roles(db)
        self._roles_cache = rows
        if term:
            match = next(
                (r for r in rows if views.fmt(r["key"]).lower() == term.lower()), None
            )
            if match is not None:
                then(match)
                return
            self.error(f"unknown role {term!r}")
            return
        by_id = {views.fmt(r["id"]): r for r in rows}
        self.choose(
            "Role",
            [
                (views.fmt(r["id"]),
                 f"{views.fmt(r['key'])}  ({views.fmt(r['perms'])}p · {views.fmt(r['assignments'])}a)")
                for r in rows
            ],
            lambda key: then(by_id[key]) if key else None,
            searchable=len(rows) > _SELECTOR_ROWS,
        )

    def _cmd_role(self, args: list[str]) -> None:
        term = args[0] if args else None
        action = args[1].lower() if len(args) > 1 else None
        if action is not None and action not in ROLE_ACTIONS:
            self.error(f"unknown action {action!r} — {' · '.join(ROLE_ACTIONS)}")
            return
        self._resolve_role(term, lambda row: self._role_action(row, action))

    def _role_action(self, row: dict[str, Any], action: str | None) -> None:
        if action is None:
            self.choose(
                views.fmt(row["key"]),
                [
                    ("show", "show — permissions + holders"),
                    ("perms", "perms — edit the permission set"),
                    ("rename", "rename — change the role key"),
                    ("delete", "delete — remove the role (cascades!)"),
                ],
                lambda key: self._role_action(row, key) if key else None,
            )
            return
        dispatch: dict[str, Callable[[dict[str, Any]], None]] = {
            "show": self._role_show,
            "perms": self._role_perms,
            "rename": self._role_rename,
            "delete": self._role_delete,
        }
        dispatch[action](row)

    def _role_show(self, row: dict[str, Any]) -> None:
        db = self._require_db()
        if db is None:
            return
        role_id = views.fmt(row["id"])
        permissions = ops.list_role_permissions(db, role_id)
        holders = [
            (
                views.fmt(a.get("email"))
                or views.fmt(a.get("display_name"))
                or views.fmt(a.get("sub"))
            )
            + (f" @ {views.fmt(a['gremium'])}" if a.get("gremium") else " (global)")
            for a in ops.list_role_users(db, role_id)
        ]
        self._log_panel.pop_out(
            views.role_detail(views.fmt(row["key"]), permissions, holders),
            f"role {views.fmt(row['key'])}",
        )

    def _role_perms(self, row: dict[str, Any]) -> None:
        db = self._writable()
        if db is None:
            return
        role_id = views.fmt(row["id"])
        current = set(ops.list_role_permissions(db, role_id))
        keys = list(dict.fromkeys([*PERMISSION_CATALOGUE, *sorted(current)]))
        fields = [
            FormField(
                key=key,
                label=key,
                kind="bool",
                choice_index=1 if key in current else 0,
                hint="⚠ human-only" if key in FORBIDDEN_PERMISSIONS else "",
            )
            for key in keys
        ]

        def submit(form: Form) -> None:
            chosen = [f.key for f in form.fields if f.choice_index]
            granted_forbidden = [k for k in chosen if k in FORBIDDEN_PERMISSIONS]

            def apply() -> None:
                self._run_write(
                    lambda d: (ops.set_role_permissions(d, role_id, chosen), len(chosen))[1],
                    f"permissions of {views.fmt(row['key'])} saved",
                )

            if granted_forbidden and not current.intersection(granted_forbidden):
                self.confirm(
                    f"{', '.join(granted_forbidden)} is human-only (never grantable "
                    "via the API). Grant anyway?",
                    apply,
                )
            else:
                apply()

        self.open_form(
            Form(title=f"permissions · {views.fmt(row['key'])}", fields=fields, on_submit=submit)
        )

    def _role_rename(self, row: dict[str, Any]) -> None:
        if self._writable() is None:
            return

        def submit(form: Form) -> None:
            key = form.by_key()["key"].text.strip()
            if not key:
                self.error("empty role key — not renamed")
                return
            self._run_write(
                lambda d: ops.rename_role(d, views.fmt(row["id"]), key),
                f"role renamed to {key}",
            )

        self.open_form(
            Form(
                title=f"rename · {views.fmt(row['key'])}",
                fields=[FormField(key="key", label="key", kind="text", text=views.fmt(row["key"]))],
                on_submit=submit,
            )
        )

    def _role_delete(self, row: dict[str, Any]) -> None:
        if self._writable() is None:
            return
        self.confirm(
            f"DELETE role {views.fmt(row['key'])}? "
            "Cascades its permissions, assignments and OIDC mappings.",
            lambda: self._run_write(
                lambda d: ops.delete_role(d, views.fmt(row["id"])), "role deleted"
            ),
        )

    def _cmd_new_role(self, args: list[str]) -> None:
        if self._writable() is None:
            return

        def create(key: str) -> None:
            key = key.strip()
            if not key:
                self.error("empty role key — not created")
                return
            self._run_write(lambda d: ops.create_role(d, key, key), f"role {key} created")

        if args:
            create(args[0])
            return
        self.open_form(
            Form(
                title="new role",
                fields=[FormField(key="key", label="key (e.g. treasurer)", kind="text")],
                on_submit=lambda form: create(form.by_key()["key"].text),
            )
        )

    def _cmd_mappings(self, _args: list[str]) -> None:
        db = self._require_db()
        if db is None:
            return
        rows = ops.list_mappings(db)
        self._mappings_cache = rows
        self._log_panel.append(
            LogEntry(fragments=views.separator(f"OIDC mappings ({len(rows)})"))
        )
        for row in views.mapping_rows(rows):
            self._log_panel.append_record(row)

    def _resolve_mapping(
        self, term: str | None, then: Callable[[dict[str, Any]], None]
    ) -> None:
        db = self._require_db()
        if db is None:
            return
        rows = ops.list_mappings(db)
        self._mappings_cache = rows
        if term:
            matches = [
                r for r in rows if term.lower() in views.fmt(r["oidc_group"]).lower()
            ]
            if len(matches) == 1:
                then(matches[0])
                return
            if not matches:
                self.error(f"no mapping matches {term!r}")
                return
            rows = matches
        by_id = {views.fmt(r["id"]): r for r in rows}
        self.choose(
            "Mapping",
            [(views.fmt(r["id"]), views.mapping_label(r)) for r in rows],
            lambda key: then(by_id[key]) if key else None,
            searchable=len(rows) > _SELECTOR_ROWS,
        )

    def _cmd_mapping(self, args: list[str]) -> None:
        term = args[0] if args else None
        action = args[1].lower() if len(args) > 1 else None
        if action is not None and action not in MAPPING_ACTIONS:
            self.error(f"unknown action {action!r} — {' · '.join(MAPPING_ACTIONS)}")
            return
        self._resolve_mapping(term, lambda row: self._mapping_action(row, action))

    def _mapping_action(self, row: dict[str, Any], action: str | None) -> None:
        if action is None:
            self.choose(
                views.mapping_label(row),
                [
                    ("show", "show — full record"),
                    ("edit", "edit — group / role / scope"),
                    ("delete", "delete — remove the mapping"),
                ],
                lambda key: self._mapping_action(row, key) if key else None,
            )
            return
        if action == "show":
            rendered = views.mapping_rows([row])
            if rendered:
                self._log_panel.pop_out(rendered[0][1], "mapping")
            return
        if action == "edit":
            self._mapping_form(row)
            return
        self.confirm(
            f"Delete mapping {views.mapping_label(row)}?",
            lambda: self._run_write(
                lambda d: ops.delete_mapping(d, views.fmt(row["id"])), "mapping deleted"
            ),
        )

    def _cmd_new_mapping(self, _args: list[str]) -> None:
        self._mapping_form(None)

    def _mapping_form(self, existing: dict[str, Any] | None) -> None:
        db = self._writable()
        if db is None:
            return
        roles = ops.list_roles_simple(db)
        if not roles:
            self.error("no roles exist yet — /new-role first")
            return
        gremien = ops.list_gremien(db)
        role_keys = [views.fmt(r["key"]) for r in roles]
        role_ids = [views.fmt(r["id"]) for r in roles]
        scope_labels = ["(global)"] + [views.fmt(g["name"]) for g in gremien]
        scope_ids: list[str | None] = [None, *(views.fmt(g["id"]) for g in gremien)]

        role_index = 0
        scope_index = 0
        if existing is not None:
            existing_role = views.fmt(existing.get("role_id"))
            if existing_role in role_ids:
                role_index = role_ids.index(existing_role)
            existing_scope = views.fmt(existing.get("gremium_id")) or None
            if existing_scope in scope_ids:
                scope_index = scope_ids.index(existing_scope)

        def submit(form: Form) -> None:
            fields = form.by_key()
            group = fields["group"].text.strip()
            if not group:
                self.error("empty OIDC group — not saved")
                return
            role_id = role_ids[fields["role"].choice_index]
            gremium_id = scope_ids[fields["scope"].choice_index]
            if existing is not None:
                mapping_id = views.fmt(existing["id"])
                self._run_write(
                    lambda d: ops.update_mapping(d, mapping_id, group, role_id, gremium_id),
                    "mapping updated",
                )
            else:
                self._run_write(
                    lambda d: ops.create_mapping(d, group, role_id, gremium_id),
                    "mapping created",
                )

        self.open_form(
            Form(
                title="edit mapping" if existing else "new mapping",
                fields=[
                    FormField(
                        key="group",
                        label="OIDC group",
                        kind="text",
                        text=views.fmt(existing["oidc_group"]) if existing else "",
                    ),
                    FormField(
                        key="role",
                        label="role",
                        kind="choice",
                        choices=role_keys,
                        choice_index=role_index,
                    ),
                    FormField(
                        key="scope",
                        label="scope",
                        kind="choice",
                        choices=scope_labels,
                        choice_index=scope_index,
                    ),
                ],
                on_submit=submit,
            )
        )

    def _cmd_audit(self, args: list[str]) -> None:
        db = self._require_db()
        if db is None:
            return
        filters: dict[str, str] = {}
        for token in args:
            key, separator, value = token.partition("=")
            if not separator:
                filters["action"] = token
                continue
            if key not in ("action", "actor", "target", "limit"):
                self.error(f"unknown audit filter {key!r} — action= actor= target= limit=")
                return
            filters[key] = value
        self._audit_filters = filters
        self._audit_oldest = None
        self._audit_last_date = ""
        self._fetch_audit(db, first_page=True)

    def _cmd_more(self, _args: list[str]) -> None:
        db = self._require_db()
        if db is None:
            return
        if self._audit_oldest is None:
            self.error("no audit page loaded — /audit first")
            return
        self._fetch_audit(db, first_page=False)

    def _audit_limit(self) -> int:
        raw = self._audit_filters.get("limit", "")
        try:
            return max(1, min(500, int(raw)))
        except ValueError:
            return _AUDIT_PAGE

    def _fetch_audit(self, db: Db, *, first_page: bool) -> None:
        filters = self._audit_filters
        rows = ops.list_audit(
            db,
            before_id=None if first_page else self._audit_oldest,
            action=filters.get("action"),
            actor=filters.get("actor"),
            target=filters.get("target"),
            limit=self._audit_limit(),
        )
        if first_page:
            active = "  ".join(f"{k}={v}" for k, v in filters.items())
            title = f"audit log{' · ' + active if active else ''}"
            self._log_panel.append(LogEntry(fragments=views.separator(title)))
        if not rows:
            self.info("no (further) audit entries")
            return
        for row in views.audit_rows(rows, self._audit_last_date):
            self._log_panel.append_record(row)
        self._audit_last_date = views.dt_parts(rows[-1].get("at"))[0]
        self._audit_oldest = int(views.fmt(rows[-1]["id"]))
        more = LogEntry(
            fragments=[
                ("class:dim", f"  {len(rows)} entries · oldest #{self._audit_oldest} · "),
                ("class:info", "/more", self._click(lambda: self._handle_line("/more"))),
                ("class:dim", " for older\n"),
            ]
        )
        self._log_panel.append(more)

    def run(self) -> None:
        """Show the startup summary and run the UI until the user quits."""
        self.info(f"antragsplattform admin v{__version__} — /help for commands")
        for note in self._startup_notes:
            (self.info if self.db is not None else self.error)(note)
        if self.db is None:
            self.error("not connected — check the stack / port forward, then /connect")
        else:
            self._refresh_caches()
            if self.cfg.read_only:
                self.info("read-only mode: writes are disabled")
            else:
                self.warn("writes bypass the API: no audit entry, no RBAC guards")
        self._app.run()


def _print(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(__version__)
        return 0
    if "-h" in args or "--help" in args:
        print(
            "antragsplattform admin-cli — manage users/roles/OIDC mappings + view the audit log.\n\n"
            "Usage: antragsplattform-admin [--read-only] [--check] [--version]\n\n"
            "DB access is resolved automatically: $DATABASE_URL if set, otherwise the\n"
            "DSN from deploy/.env rewritten to localhost:<port published in the compose\n"
            "file> (works on the VM and through an SSH port-forward), otherwise\n"
            "`docker compose exec postgres psql` against the running stack.\n"
            "Env overrides: DATABASE_URL, COMPOSE_FILE, ENV_FILE, POSTGRES_SERVICE,\n"
            "POSTGRES_USER, POSTGRES_DB."
        )
        return 0

    cfg = resolve(read_only="--read-only" in args)
    db, notes = connect_auto(cfg)

    if "--check" in args:
        for note in notes:
            _print(("ok: " if db is not None else "--  ") + note)
        if db is None:
            _print("error: no database reachable")
            return 2
        rows = db.query("SELECT count(*) AS n FROM principal")
        _print(f"ok: {rows[0]['n']} principals.")
        db.close()
        return 0

    cli = AdminCLI(cfg, db, notes)
    try:
        cli.run()
    finally:
        # /connect may have swapped the backend. Close whatever the UI holds now.
        if cli.db is not None:
            cli.db.close()
    return 0
