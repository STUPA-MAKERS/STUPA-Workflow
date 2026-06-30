"""Full-screen prompt_toolkit TUI (mouse + keyboard).

Layout: header · [ left menu | section body ] · footer. The body is swapped per section
(Users / Roles / OIDC mappings / Audit). Modal dialogs (confirm / input / choose / checkboxes)
are pushed as floats. Every mutation goes through a confirm dialog. DB writes bypass the API →
no audit entry, no RBAC guards (shown in the footer).
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.layout import (
    DynamicContainer,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import (
    Box,
    Button,
    CheckboxList,
    Dialog,
    Frame,
    Label,
    RadioList,
    TextArea,
)

from . import __version__, ops
from .config import Config, load
from .db import Db, DbError, connect
from .permissions import FORBIDDEN_PERMISSIONS, PERMISSION_CATALOGUE

_STYLE = Style.from_dict(
    {
        "frame.border": "#5f87af",
        "header": "bg:#005f87 #ffffff bold",
        "footer": "bg:#262626 #b2b2b2",
        "footer.warn": "bg:#262626 #ffaf00",
        "menu.btn": "#d0d0d0",
        "dialog.body": "#d0d0d0",
        "dialog frame.label": "#ffaf00 bold",
        "button.focused": "bg:#005f87 #ffffff",
    }
)

_SECTIONS = [("users", "Users"), ("roles", "Roles"), ("oidc", "OIDC mappings"), ("audit", "Audit log")]


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


class AdminApp:
    def __init__(self, db: Db, cfg: Config) -> None:
        self.db = db
        self.cfg = cfg
        self.section = "users"
        self._floats: list[Float] = []
        self._body: Any = Window()
        self._focus_target: Any = None
        self._status = ""
        # audit paging state
        self._audit_before: int | None = None
        self._audit_action: str | None = None
        self._audit_rows: list[dict[str, Any]] = []

        menu = Box(
            HSplit(
                [Button(text=label, handler=lambda s=key: self.goto(s), width=18) for key, label in _SECTIONS]
                + [
                    Window(height=1),
                    Button(text="Refresh (F5)", handler=self.refresh, width=18),
                    Button(text="Quit (^Q)", handler=self.exit, width=18),
                ],
                padding=0,
            ),
            padding=1,
            style="class:menu.btn",
        )
        root = FloatContainer(
            content=HSplit(
                [
                    Window(FormattedTextControl(self._header_text), height=1, style="class:header"),
                    VSplit(
                        [
                            Frame(menu, width=24),
                            Frame(DynamicContainer(lambda: self._body)),
                        ],
                        padding=0,
                    ),
                    Window(FormattedTextControl(self._footer_text), height=1, style="class:footer"),
                ]
            ),
            floats=self._floats,
        )
        self.kb = self._key_bindings()
        self.app: Application = Application(
            layout=Layout(root),
            key_bindings=self.kb,
            style=_STYLE,
            mouse_support=True,
            full_screen=True,
        )
        self.goto("users")

    # ------------------------------------------------------------------ chrome
    def _header_text(self) -> Any:
        return [("class:header", f" antragsplattform admin-cli {__version__} — "
                 f"{dict(_SECTIONS)[self.section]} ")]

    def _footer_text(self) -> Any:
        warn = " READ-ONLY " if self.cfg.read_only else " DIRECT DB: no audit, no guards "
        cls = "class:footer" if self.cfg.read_only else "class:footer.warn"
        msg = self._status or "Tab/↑↓ move · Enter/click select · F5 refresh · ^Q quit"
        return [
            (cls, warn),
            ("class:footer", f" db={self.cfg.mode_label} · {msg} "),
        ]

    def set_status(self, text: str) -> None:
        self._status = text
        self.app.invalidate()

    def _key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        kb.add("tab")(focus_next)
        kb.add("s-tab")(focus_previous)

        @kb.add("c-q")
        @kb.add("c-c")
        def _(event: Any) -> None:
            event.app.exit()

        @kb.add("f5")
        def _(event: Any) -> None:
            self.refresh()

        return kb

    def exit(self) -> None:
        self.app.exit()

    # ------------------------------------------------------------------ floats / dialogs
    def _open(self, dialog: Dialog, focus: Any = None) -> None:
        flt = Float(content=dialog)
        self._floats.append(flt)
        self.app.layout.focus(focus or dialog)
        self.app.invalidate()

    def _close(self) -> None:
        if self._floats:
            self._floats.pop()
        target = self._focus_target
        if self._floats:
            self.app.layout.focus(self._floats[-1].content)
        elif target is not None:
            try:
                self.app.layout.focus(target)
            except Exception:  # noqa: BLE001 - focus target may have been rebuilt
                pass
        self.app.invalidate()

    def message(self, text: str, title: str = "Info") -> None:
        self._open(Dialog(title=title, body=Label(text=text), buttons=[Button("OK", self._close)], modal=True))

    def confirm(self, text: str, on_yes: Callable[[], Any], title: str = "Confirm") -> None:
        def yes() -> None:
            self._close()
            on_yes()

        self._open(
            Dialog(
                title=title,
                body=Label(text=text),
                buttons=[Button("Yes", yes), Button("No", self._close)],
                modal=True,
            )
        )

    def ask_input(
        self, title: str, label: str, default: str, on_ok: Callable[[str], Any]
    ) -> None:
        area = TextArea(text=default, multiline=False, width=D(min=30))

        def ok() -> None:
            value = area.text.strip()
            self._close()
            on_ok(value)

        body = HSplit([Label(text=label), Frame(area)])
        self._open(
            Dialog(title=title, body=body, buttons=[Button("OK", ok), Button("Cancel", self._close)], modal=True),
            focus=area,
        )

    def ask_choice(
        self,
        title: str,
        values: Sequence[tuple[Any, str]],
        on_ok: Callable[[Any], Any],
        *,
        label: str = "Select:",
    ) -> None:
        if not values:
            self.message("Nothing to choose from.")
            return
        radio: RadioList = RadioList(values=list(values))

        def ok() -> None:
            value = radio.current_value
            self._close()
            on_ok(value)

        body = HSplit([Label(text=label), radio])
        self._open(
            Dialog(title=title, body=body, buttons=[Button("OK", ok), Button("Cancel", self._close)], modal=True),
            focus=radio,
        )

    def ask_checkboxes(
        self,
        title: str,
        values: Sequence[tuple[Any, str]],
        preselected: Sequence[Any],
        on_ok: Callable[[list[Any]], Any],
    ) -> None:
        cb: CheckboxList = CheckboxList(values=list(values))
        cb.current_values = list(preselected)

        def ok() -> None:
            chosen = list(cb.current_values)
            self._close()
            on_ok(chosen)

        self._open(
            Dialog(
                title=title,
                body=HSplit([Label(text="Space toggles · Enter on OK saves"), cb], height=D(max=24)),
                buttons=[Button("OK", ok), Button("Cancel", self._close)],
                modal=True,
                width=D(min=48),
            ),
            focus=cb,
        )

    def guard_write(self, action: Callable[[], None]) -> None:
        if self.cfg.read_only:
            self.message("Started in --read-only mode; writes are disabled.")
            return
        action()

    def run_write(self, do: Callable[[], int], success: str) -> None:
        try:
            n = do()
        except DbError as exc:
            self.message(str(exc), title="DB error")
            return
        self.set_status(f"{success} ({n} row(s))")
        self.refresh()

    # ------------------------------------------------------------------ navigation
    def goto(self, section: str) -> None:
        self.section = section
        self.refresh()

    def refresh(self) -> None:
        try:
            {"users": self._build_users, "roles": self._build_roles,
             "oidc": self._build_oidc, "audit": self._build_audit}[self.section]()
        except DbError as exc:
            self._body = Box(Label(text=f"DB error:\n{exc}"))
        self.app.invalidate()

    def _set_body(self, container: Any, focus: Any) -> None:
        self._body = container
        self._focus_target = focus
        if not self._floats:
            try:
                self.app.layout.focus(focus)
            except Exception:  # noqa: BLE001
                pass

    def _list_or_empty(self, values: Sequence[tuple[Any, str]]) -> tuple[Any, Any]:
        """Return (control, focus_target). RadioList needs ≥1 entry."""
        if not values:
            label = Label(text="  (no entries)")
            return label, label
        radio: RadioList = RadioList(values=list(values))
        return radio, radio

    # ------------------------------------------------------------------ USERS
    def _build_users(self) -> None:
        rows = ops.list_users(self.db, self._user_search if hasattr(self, "_user_search") else None)
        self._users = rows
        values = [
            (
                r["id"],
                f"{'●' if str(r['active']) in ('True', 't', 'true') else '○'} "
                f"{_fmt(r['email']) or _fmt(r['display_name']) or _fmt(r['sub'])}"
                + (f"   [{r['roles']}]" if r["roles"] else "   [—]"),
            )
            for r in rows
        ]
        control, focus = self._list_or_empty(values)
        self._users_list = control

        def selected_id() -> str | None:
            return getattr(control, "current_value", None)

        def search() -> None:
            self.ask_input("Search users", "email / name / sub contains:", "", self._do_user_search)

        def roles() -> None:
            uid = selected_id()
            if uid:
                self._user_roles_dialog(uid)

        def toggle() -> None:
            uid = selected_id()
            if not uid:
                return
            row = next((u for u in rows if u["id"] == uid), None)
            active = str(row["active"]) in ("True", "t", "true") if row else False
            label = _fmt(row["email"] or row["display_name"] or row["sub"]) if row else uid
            self.guard_write(lambda: self.confirm(
                f"{'Deactivate' if active else 'Activate'} {label}?",
                lambda: self.run_write(lambda: ops.set_user_active(self.db, uid, not active), "user updated"),
            ))

        def delete() -> None:
            uid = selected_id()
            if not uid:
                return
            row = next((u for u in rows if u["id"] == uid), None)
            label = _fmt(row["email"] or row["display_name"] or row["sub"]) if row else uid
            self.guard_write(lambda: self.confirm(
                f"DELETE principal {label}?\nThis cascades sessions + role assignments. Irreversible.",
                lambda: self.run_write(lambda: ops.delete_user(self.db, uid), "user deleted"),
                title="Delete user",
            ))

        buttons = VSplit(
            [
                Button("Search", search, width=10),
                Button("Roles…", roles, width=10),
                Button("Toggle active", toggle, width=16),
                Button("Delete", delete, width=10),
            ],
            padding=1,
        )
        body = HSplit([Box(control, padding=0), Window(height=1), buttons])
        self._set_body(body, focus)

    def _do_user_search(self, term: str) -> None:
        self._user_search = term or None
        self.refresh()

    def _user_roles_dialog(self, principal_id: str) -> None:
        assignments = ops.list_user_roles(self.db, principal_id)
        values = [
            (
                a["id"],
                f"{a['role_key']}" + (f" @ {a['gremium']}" if a["gremium"] else " (global)"),
            )
            for a in assignments
        ]
        radio_control, focus = self._list_or_empty(values)

        def revoke() -> None:
            aid = getattr(radio_control, "current_value", None)
            if not aid:
                return

            def do() -> None:
                self._close()  # close the roles dialog
                self.run_write(lambda: ops.revoke_assignment(self.db, aid), "assignment revoked")
                self._user_roles_dialog(principal_id)  # reopen, refreshed

            self.guard_write(lambda: self.confirm("Revoke this role assignment?", do))

        def add() -> None:
            self._add_role_flow(principal_id)

        body = HSplit([Label(text="Assignments:"), radio_control], height=D(max=20))
        self._open(
            Dialog(
                title="User roles",
                body=body,
                buttons=[Button("Add…", add), Button("Revoke", revoke), Button("Close", self._close)],
                modal=True,
                width=D(min=50),
            ),
            focus=focus,
        )

    def _add_role_flow(self, principal_id: str) -> None:
        roles = ops.list_roles_simple(self.db)
        role_values = [(r["id"], r["key"]) for r in roles]

        def pick_role(role_id: Any) -> None:
            gremien = ops.list_gremien(self.db)
            g_values: list[tuple[Any, str]] = [(None, "(global)")]
            g_values += [(g["id"], _fmt(g["name"])) for g in gremien]

            def pick_gremium(gremium_id: Any) -> None:
                self.guard_write(lambda: self.run_write(
                    lambda: ops.grant_role(self.db, principal_id, role_id, gremium_id),
                    "role granted",
                ))
                self._user_roles_dialog(principal_id)

            self.ask_choice("Scope", g_values, pick_gremium, label="Gremium (or global):")

        self.ask_choice("Add role", role_values, pick_role, label="Role:")

    # ------------------------------------------------------------------ ROLES
    def _build_roles(self) -> None:
        rows = ops.list_roles(self.db)
        values = [
            (r["id"], f"{r['key']}   ({r['perms']} perms, {r['assignments']} assignments)")
            for r in rows
        ]
        control, focus = self._list_or_empty(values)

        def sel() -> Any:
            return getattr(control, "current_value", None)

        def perms() -> None:
            rid = sel()
            if rid:
                self._role_perms_dialog(rid, next((r["key"] for r in rows if r["id"] == rid), ""))

        def new() -> None:
            self.guard_write(lambda: self.ask_input(
                "New role", "Role key (e.g. treasurer):", "",
                lambda key: key and self.run_write(
                    lambda: ops.create_role(self.db, key, key), "role created"),
            ))

        def rename() -> None:
            rid = sel()
            if not rid:
                return
            cur = next((r["key"] for r in rows if r["id"] == rid), "")
            self.guard_write(lambda: self.ask_input(
                "Rename role", "New key:", cur,
                lambda key: key and self.run_write(
                    lambda: ops.rename_role(self.db, rid, key, key), "role renamed"),
            ))

        def delete() -> None:
            rid = sel()
            if not rid:
                return
            cur = next((r["key"] for r in rows if r["id"] == rid), "")
            self.guard_write(lambda: self.confirm(
                f"DELETE role '{cur}'?\nCascades its permissions, assignments and OIDC mappings.",
                lambda: self.run_write(lambda: ops.delete_role(self.db, rid), "role deleted"),
                title="Delete role",
            ))

        buttons = VSplit(
            [Button("Permissions…", perms, width=15), Button("New", new, width=8),
             Button("Rename", rename, width=10), Button("Delete", delete, width=10)],
            padding=1,
        )
        self._set_body(HSplit([Box(control, padding=0), Window(height=1), buttons]), focus)

    def _role_perms_dialog(self, role_id: str, role_key: str) -> None:
        current = set(ops.list_role_permissions(self.db, role_id))
        keys = list(dict.fromkeys([*PERMISSION_CATALOGUE, *sorted(current)]))
        values = [
            (k, k + ("  ⚠ human-only" if k in FORBIDDEN_PERMISSIONS else "")) for k in keys
        ]

        def save(chosen: list[Any]) -> None:
            def do() -> int:
                perms = [str(c) for c in chosen]
                ops.set_role_permissions(self.db, role_id, perms)
                return len(perms)

            self.guard_write(lambda: self.run_write(do, "permissions saved"))

        self.ask_checkboxes(f"Permissions · {role_key}", values, sorted(current), save)

    # ------------------------------------------------------------------ OIDC mappings
    def _build_oidc(self) -> None:
        rows = ops.list_mappings(self.db)
        values = [
            (r["id"], f"{r['oidc_group']} → {r['role_key']}"
             + (f" @ {r['gremium']}" if r["gremium"] else " (global)"))
            for r in rows
        ]
        control, focus = self._list_or_empty(values)

        def sel() -> Any:
            return getattr(control, "current_value", None)

        def new() -> None:
            self.guard_write(lambda: self._mapping_flow(None))

        def edit() -> None:
            mid = sel()
            if mid:
                self.guard_write(lambda: self._mapping_flow(next((r for r in rows if r["id"] == mid), None)))

        def delete() -> None:
            mid = sel()
            if not mid:
                return
            self.guard_write(lambda: self.confirm(
                "Delete this OIDC group-mapping?",
                lambda: self.run_write(lambda: ops.delete_mapping(self.db, mid), "mapping deleted"),
            ))

        buttons = VSplit(
            [Button("New", new, width=8), Button("Edit", edit, width=8), Button("Delete", delete, width=10)],
            padding=1,
        )
        self._set_body(HSplit([Box(control, padding=0), Window(height=1), buttons]), focus)

    def _mapping_flow(self, existing: dict[str, Any] | None) -> None:
        roles = ops.list_roles_simple(self.db)
        role_values = [(r["id"], r["key"]) for r in roles]
        mapping_id: Any = existing["id"] if existing else None
        default_group = _fmt(existing["oidc_group"]) if existing else ""

        def got_group(group: str) -> None:
            if not group:
                return

            def got_role(role_id: Any) -> None:
                gremien = ops.list_gremien(self.db)
                g_values: list[tuple[Any, str]] = [(None, "(global)")]
                g_values += [(g["id"], _fmt(g["name"])) for g in gremien]

                def got_gremium(gremium_id: Any) -> None:
                    if mapping_id is not None:
                        self.run_write(
                            lambda: ops.update_mapping(self.db, mapping_id, group, role_id, gremium_id),
                            "mapping updated")
                    else:
                        self.run_write(
                            lambda: ops.create_mapping(self.db, group, role_id, gremium_id),
                            "mapping created")

                self.ask_choice("Scope", g_values, got_gremium, label="Gremium (or global):")

            self.ask_choice("Role", role_values, got_role, label="Maps to role:")

        self.ask_input(
            "OIDC mapping" + (" (edit)" if existing else " (new)"),
            "OIDC group name:", default_group, got_group,
        )

    # ------------------------------------------------------------------ AUDIT
    def _build_audit(self) -> None:
        if self._audit_before is None:
            self._audit_rows = ops.list_audit(self.db, action=self._audit_action, limit=100)
        text = self._format_audit(self._audit_rows)
        area = TextArea(text=text, read_only=True, scrollbar=True, focus_on_click=True, wrap_lines=False)

        def more() -> None:
            if not self._audit_rows:
                return
            last_id = int(self._audit_rows[-1]["id"])
            extra = ops.list_audit(self.db, before_id=last_id, action=self._audit_action, limit=100)
            self._audit_rows += extra
            self.refresh()
            self.set_status(f"loaded {len(self._audit_rows)} entries")

        def filt() -> None:
            self.ask_input(
                "Filter audit", "action contains (empty = all):", self._audit_action or "",
                self._do_audit_filter,
            )

        buttons = VSplit(
            [Button("Load more", more, width=12), Button("Filter…", filt, width=10),
             Button("Reset", self._reset_audit, width=8)],
            padding=1,
        )
        self._set_body(HSplit([area, Window(height=1), buttons]), area)

    def _do_audit_filter(self, term: str) -> None:
        self._audit_action = term or None
        self._audit_rows = []
        self.refresh()

    def _reset_audit(self) -> None:
        self._audit_action = None
        self._audit_rows = []
        self.refresh()

    @staticmethod
    def _format_audit(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "(no audit entries)"
        out = []
        for r in rows:
            tgt = f" {r['target_type']}:{r['target_id']}" if r["target_type"] else ""
            out.append(
                f"#{r['id']:>8}  {_fmt(r['at'])[:19]}  {_fmt(r['actor']) or '—':<28} "
                f"{_fmt(r['action'])}{tgt}"
            )
            data = _fmt(r["data"])
            if data and data not in ("{}", "null"):
                out.append(f"           {data}")
        return "\n".join(out)

    def run(self) -> None:
        self.app.run()


def _print(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(__version__)
        return 0
    if "-h" in args or "--help" in args:
        print(
            "antragsplattform admin-cli — manage users/roles/OIDC mappings + view audit log.\n\n"
            "Usage: antragsplattform-admin [--read-only] [--check] [--version]\n\n"
            "DB access: set DATABASE_URL for a direct connection, otherwise the running stack is\n"
            "reached via `docker compose -f $COMPOSE_FILE exec postgres psql` (default compose file\n"
            "deploy/docker-compose.yml). Env: COMPOSE_FILE, POSTGRES_SERVICE, POSTGRES_USER, POSTGRES_DB."
        )
        return 0

    cfg = load(read_only="--read-only" in args)
    try:
        db = connect(cfg)
    except DbError as exc:
        _print(f"error: {exc}")
        return 2

    if "--check" in args:
        try:
            rows = db.query("SELECT count(*) AS n FROM principal")
            _print(f"ok: connected via {cfg.mode_label}; {rows[0]['n']} principals.")
            return 0
        except DbError as exc:
            _print(f"error: {exc}")
            return 2
        finally:
            db.close()

    try:
        AdminApp(db, cfg).run()
    finally:
        db.close()
    return 0
