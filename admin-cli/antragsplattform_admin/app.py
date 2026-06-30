"""Full-screen prompt_toolkit TUI (mouse + keyboard).

Layout: header · top tab bar (Users / Roles / OIDC / Audit) · master-detail body · footer.
Each section is a left **list** of items + a right **detail** pane whose sub-tabs depend on the
selected item (user → Roles / Actions; role → Permissions / Users / Actions; mapping → Actions).
Audit is a single full-width formatted, paged table. Pickers (add role, choose scope) still use
modal floats. DB writes bypass the API → no audit entry, no RBAC guards (shown in the footer).
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.filters import to_filter
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
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
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

# Claude-Code-inspired palette: signature coral accent on a near-black neutral base.
_CORAL = "#d97757"
_INK = "#1a1a1a"
_FG = "#e8e6e3"
_DIM = "#8a8a8a"
_LINE = "#3a3a3a"

_STYLE = Style.from_dict(
    {
        # structural frames + rules
        "frame.border": _LINE,
        "frame.label": f"{_CORAL} bold",
        "rule": _LINE,
        # header / brand bar
        "header": f"bg:{_INK} {_FG}",
        "header.brand": f"bg:{_INK} {_CORAL} bold",
        "header.dim": f"bg:{_INK} {_DIM}",
        # top tab strip
        "tabbar": f"bg:{_INK}",
        "tab": f"bg:{_INK} {_DIM}",
        "tab.active": f"bg:{_CORAL} {_INK} bold",
        # detail sub-tabs
        "subtab": f"bg:{_INK} {_DIM}",
        "subtab.active": f"bg:{_INK} {_CORAL} bold",
        # footer / status line
        "footer": "bg:#222222 #9e9e9e",
        "footer.ro": "bg:#1f3a2a #87d7af bold",
        "footer.warn": "bg:#5a2310 #ffd7af bold",
        "footer.key": "bg:#222222 #d7d7d7 bold",
        # detail headings
        "detail.head": f"{_CORAL} bold",
        "detail.dim": _DIM,
        # interactive widgets
        "button": _FG,
        "button.focused": f"bg:{_CORAL} {_INK} bold",
        "button.arrow": _DIM,
        "radio": _FG,
        "radio-selected": f"{_CORAL} bold",
        "radio-checked": f"{_CORAL} bold",
        "checkbox": _FG,
        "checkbox-selected": f"{_CORAL} bold",
        "checkbox-checked": f"{_CORAL} bold",
        # dialogs / floats
        "dialog": f"bg:{_INK}",
        "dialog.body": _FG,
        "dialog frame.label": f"{_CORAL} bold",
        "dialog shadow": "bg:#000000",
    }
)

_SECTIONS = [("users", "Users"), ("roles", "Roles"), ("oidc", "OIDC mappings"), ("audit", "Audit log")]

# Sub-tabs shown in the right detail pane, per section. Audit has none (full-width table).
_SUBTABS: dict[str, list[tuple[str, str]]] = {
    "users": [("roles", "Roles"), ("actions", "Actions")],
    "roles": [("perms", "Permissions"), ("users", "Users"), ("actions", "Actions")],
    "oidc": [("actions", "Actions")],
}


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


def _truthy(value: Any) -> bool:
    return str(value) in ("True", "t", "true")


class AdminApp:
    def __init__(self, db: Db, cfg: Config) -> None:
        self.db = db
        self.cfg = cfg
        self.section = "users"
        self._floats: list[Float] = []
        self._body: Any = Window()
        self._focus_target: Any = None
        self._status = ""
        # master-detail state
        self._subtab: dict[str, str] = {"users": "roles", "roles": "perms", "oidc": "actions"}
        self._selected: dict[str, Any] = {}
        self._left_ctrl: Any = None
        self._detail_cache: tuple[tuple[Any, ...], Any] | None = None
        # per-section caches populated by the builders
        self._users: list[dict[str, Any]] = []
        self._roles: list[dict[str, Any]] = []
        self._mappings: list[dict[str, Any]] = []
        self._perm_cb: CheckboxList | None = None
        # audit paging state
        self._audit_action: str | None = None
        self._audit_rows: list[dict[str, Any]] = []

        self._detail = {
            ("users", "roles"): self._detail_users_roles,
            ("users", "actions"): self._detail_users_actions,
            ("roles", "perms"): self._detail_roles_perms,
            ("roles", "users"): self._detail_roles_users,
            ("roles", "actions"): self._detail_roles_actions,
            ("oidc", "actions"): self._detail_oidc_actions,
        }

        root = FloatContainer(
            content=HSplit(
                [
                    Window(FormattedTextControl(self._header_text), height=1, style="class:header"),
                    Window(
                        FormattedTextControl(self._tabbar_fragments, focusable=False),
                        height=1,
                        style="class:tabbar",
                    ),
                    DynamicContainer(lambda: self._body),
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
        return [
            ("class:header.brand", " ✻ "),
            ("class:header", "antragsplattform "),
            ("class:header.dim", f"admin-cli v{__version__}"),
        ]

    def _tabbar_fragments(self) -> Any:
        frags: list[Any] = [("class:tabbar", " ")]
        for key, label in _SECTIONS:
            active = key == self.section

            def handler(mouse_event: MouseEvent, target: str = key) -> None:
                if mouse_event.event_type == MouseEventType.MOUSE_UP:
                    self.goto(target)

            cls = "class:tab.active" if active else "class:tab"
            frags.append((cls, f"  {label}  ", handler))
            frags.append(("class:tabbar", " "))
        return frags

    def _subtab_fragments(self) -> Any:
        cur = self._subtab.get(self.section)
        frags: list[Any] = [("class:subtab", " ")]
        for key, label in _SUBTABS.get(self.section, []):
            active = key == cur

            def handler(mouse_event: MouseEvent, target: str = key) -> None:
                if mouse_event.event_type == MouseEventType.MOUSE_UP:
                    self._goto_subtab(target)

            cls = "class:subtab.active" if active else "class:subtab"
            frags.append((cls, f" {'▸ ' if active else ''}{label} ", handler))
            frags.append(("class:subtab", " "))
        return frags

    def _footer_text(self) -> Any:
        if self.cfg.read_only:
            badge = ("class:footer.ro", " ● READ-ONLY ")
        else:
            badge = ("class:footer.warn", " ⚠ DIRECT DB — no audit, no guards ")
        msg = self._status or "^←/^→ tabs · Tab/↑↓ move · Enter/click select · F5 refresh · ^Q quit"
        return [
            badge,
            ("class:footer", f"  db={self.cfg.mode_label}  "),
            ("class:footer.key", "·"),
            ("class:footer", f"  {msg} "),
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
        def _(_event: Any) -> None:
            self.refresh()

        @kb.add("c-right")
        def _(_event: Any) -> None:
            self._cycle(1)

        @kb.add("c-left")
        def _(_event: Any) -> None:
            self._cycle(-1)

        return kb

    def _cycle(self, delta: int) -> None:
        keys = [k for k, _ in _SECTIONS]
        self.goto(keys[(keys.index(self.section) + delta) % len(keys)])

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

    def _goto_subtab(self, key: str) -> None:
        self._subtab[self.section] = key
        self._detail_cache = None
        self.app.invalidate()

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

    def _list_or_empty(
        self, values: Sequence[tuple[Any, str]], default: Any = None, *, fill: bool = False
    ) -> tuple[Any, Any]:
        """Return (control, focus_target). RadioList needs ≥1 entry. ``fill`` lets the list grow
        to consume the available vertical space (its base widget is dont_extend_height by default)."""
        if not values:
            label = Label(text="  (no entries)")
            return HSplit([label, Window()]), label
        keys = [v[0] for v in values]
        radio: RadioList = RadioList(values=list(values), default=default if default in keys else None)
        if fill:
            radio.window.dont_extend_height = to_filter(False)
            radio.window.dont_extend_width = to_filter(False)
        return radio, radio

    # ------------------------------------------------------------------ master-detail shell
    def _master_detail(self, left_content: Any, focus: Any, *, left_title: str) -> None:
        self._detail_cache = None
        right = HSplit(
            [
                Window(
                    FormattedTextControl(self._subtab_fragments, focusable=False),
                    height=1,
                    style="class:subtab",
                ),
                Window(height=1, char="─", style="class:rule"),
                DynamicContainer(self._detail_body),
            ]
        )
        # Left list holds the long rows → give it the bulk of the width; the detail pane is short,
        # so cap it so it doesn't leave a dead zone on wide terminals.
        body = VSplit(
            [
                Frame(left_content, title=left_title, width=D(weight=1, min=40)),
                Frame(right, title="Details", width=D(min=42, max=64)),
            ],
            padding=0,
        )
        self._set_body(body, focus)

    def _detail_body(self) -> Any:
        section = self.section
        sel = getattr(self._left_ctrl, "current_value", None)
        if sel is not None:
            self._selected[section] = sel
        sub = self._subtab.get(section)
        key = (section, sub, sel)
        if self._detail_cache is not None and self._detail_cache[0] == key:
            return self._detail_cache[1]
        builder = self._detail.get((section, sub or ""))
        container = builder(sel) if builder else Box(Label("—"))
        self._detail_cache = (key, container)
        return container

    @staticmethod
    def _placeholder(text: str) -> Any:
        return HSplit([Box(Label(text=text), padding=1), Window()])

    @staticmethod
    def _heading(text: str) -> Any:
        return Window(FormattedTextControl([("class:detail.head", text)]), height=1)

    # ------------------------------------------------------------------ USERS
    def _user_label(self, r: dict[str, Any]) -> str:
        dot = "●" if _truthy(r["active"]) else "○"
        name = _fmt(r["email"]) or _fmt(r["display_name"]) or _fmt(r["sub"])
        roles = f"   [{r['roles']}]" if r["roles"] else "   [—]"
        return f"{dot} {name}{roles}"

    def _build_users(self) -> None:
        rows = ops.list_users(self.db, getattr(self, "_user_search", None))
        self._users = rows
        values = [(r["id"], self._user_label(r)) for r in rows]
        ctrl, focus = self._list_or_empty(values, self._selected.get("users"), fill=True)
        self._left_ctrl = ctrl
        search = getattr(self, "_user_search", None)
        title = f"Users ({len(rows)})" + (f" · filter “{search}”" if search else "")
        search_btn = Button("Search / filter…", self._user_search_dialog, width=22)
        left = HSplit([search_btn, Window(height=1), ctrl])
        self._master_detail(left, focus, left_title=title)

    def _user_search_dialog(self) -> None:
        self.ask_input(
            "Search users", "email / name / sub contains:",
            getattr(self, "_user_search", None) or "", self._do_user_search,
        )

    def _do_user_search(self, term: str) -> None:
        self._user_search = term or None
        self._selected.pop("users", None)
        self.refresh()

    def _detail_users_roles(self, uid: Any) -> Any:
        if not uid:
            return self._placeholder("Select a user on the left to manage its roles.")
        rows = ops.list_user_roles(self.db, uid)
        values = [
            (a["id"], f"{a['role_key']}" + (f" @ {a['gremium']}" if a["gremium"] else " (global)"))
            for a in rows
        ]
        ctrl, _focus = self._list_or_empty(values, fill=True)

        def add() -> None:
            self.guard_write(lambda: self._add_role_flow(uid))

        def revoke() -> None:
            aid = getattr(ctrl, "current_value", None)
            if not aid:
                return
            self.guard_write(lambda: self.confirm(
                "Revoke this role assignment?",
                lambda: self.run_write(lambda: ops.revoke_assignment(self.db, aid), "assignment revoked"),
            ))

        buttons = VSplit([Button("Add…", add, width=9), Button("Revoke", revoke, width=10)], padding=1)
        return HSplit([
            self._heading(f"Role assignments ({len(rows)})"),
            ctrl,
            Window(height=1),
            buttons,
        ])

    def _detail_users_actions(self, uid: Any) -> Any:
        if not uid:
            return self._placeholder("Select a user on the left.")
        row = next((u for u in self._users if u["id"] == uid), None)
        if row is None:
            return self._placeholder("User not found — refresh.")
        active = _truthy(row["active"])
        label = _fmt(row["email"] or row["display_name"] or row["sub"])
        info = "\n".join([
            f"Name   {label}",
            f"Sub    {_fmt(row['sub'])}",
            f"Active {'yes' if active else 'no'}",
            f"Roles  {_fmt(row['roles']) or '—'}",
            f"Last   {_fmt(row['last_login'])[:19] or 'never'}",
        ])

        def toggle() -> None:
            self.guard_write(lambda: self.confirm(
                f"{'Deactivate' if active else 'Activate'} {label}?",
                lambda: self.run_write(lambda: ops.set_user_active(self.db, uid, not active), "user updated"),
            ))

        def delete() -> None:
            self.guard_write(lambda: self.confirm(
                f"DELETE principal {label}?\nCascades sessions + role assignments. Irreversible.",
                lambda: self.run_write(lambda: ops.delete_user(self.db, uid), "user deleted"),
                title="Delete user",
            ))

        buttons = VSplit(
            [Button("Activate" if not active else "Deactivate", toggle, width=14),
             Button("Delete", delete, width=10)],
            padding=1,
        )
        return HSplit([self._heading("User"), Box(Label(info), padding=0), Window(height=1), buttons, Window()])

    def _add_role_flow(self, principal_id: str) -> None:
        roles = ops.list_roles_simple(self.db)
        role_values = [(r["id"], r["key"]) for r in roles]

        def pick_role(role_id: Any) -> None:
            gremien = ops.list_gremien(self.db)
            g_values: list[tuple[Any, str]] = [(None, "(global)")]
            g_values += [(g["id"], _fmt(g["name"])) for g in gremien]

            def pick_gremium(gremium_id: Any) -> None:
                self.run_write(
                    lambda: ops.grant_role(self.db, principal_id, role_id, gremium_id),
                    "role granted",
                )

            self.ask_choice("Scope", g_values, pick_gremium, label="Gremium (or global):")

        self.ask_choice("Add role", role_values, pick_role, label="Role:")

    # ------------------------------------------------------------------ ROLES
    def _build_roles(self) -> None:
        rows = ops.list_roles(self.db)
        self._roles = rows
        values = [(r["id"], f"{r['key']}   ({r['perms']}p · {r['assignments']}a)") for r in rows]
        ctrl, focus = self._list_or_empty(values, self._selected.get("roles"), fill=True)
        self._left_ctrl = ctrl
        new_btn = Button("New role…", self._new_role, width=22)
        left = HSplit([new_btn, Window(height=1), ctrl])
        self._master_detail(left, focus, left_title=f"Roles ({len(rows)})")

    def _role_key(self, rid: Any) -> str:
        return next((r["key"] for r in self._roles if r["id"] == rid), "")

    def _detail_roles_perms(self, rid: Any) -> Any:
        if not rid:
            return self._placeholder("Select a role on the left.")
        current = set(ops.list_role_permissions(self.db, rid))
        keys = list(dict.fromkeys([*PERMISSION_CATALOGUE, *sorted(current)]))
        values = [(k, k + ("  ⚠ human-only" if k in FORBIDDEN_PERMISSIONS else "")) for k in keys]
        cb: CheckboxList = CheckboxList(values=values)
        cb.current_values = sorted(current)
        cb.window.dont_extend_height = to_filter(False)
        cb.window.dont_extend_width = to_filter(False)
        self._perm_cb = cb

        def save() -> None:
            chosen = [str(c) for c in cb.current_values]

            def do() -> int:
                ops.set_role_permissions(self.db, rid, chosen)
                return len(chosen)

            self.guard_write(lambda: self.run_write(do, "permissions saved"))

        return HSplit([
            self._heading(f"Permissions · {self._role_key(rid)}"),
            Window(FormattedTextControl([("class:detail.dim", "Space toggles · Save to apply")]), height=1),
            cb,
            Window(height=1),
            VSplit([Button("Save", save, width=9)], padding=1),
        ])

    def _detail_roles_users(self, rid: Any) -> Any:
        if not rid:
            return self._placeholder("Select a role on the left.")
        rows = ops.list_role_users(self.db, rid)
        values = [
            (
                a["assignment_id"],
                f"{_fmt(a['email']) or _fmt(a['display_name']) or _fmt(a['sub'])}"
                + (f" @ {a['gremium']}" if a["gremium"] else " (global)"),
            )
            for a in rows
        ]
        ctrl, _focus = self._list_or_empty(values, fill=True)

        def revoke() -> None:
            aid = getattr(ctrl, "current_value", None)
            if not aid:
                return
            self.guard_write(lambda: self.confirm(
                "Revoke this principal's assignment of this role?",
                lambda: self.run_write(lambda: ops.revoke_assignment(self.db, aid), "assignment revoked"),
            ))

        return HSplit([
            self._heading(f"Principals with “{self._role_key(rid)}” ({len(rows)})"),
            ctrl,
            Window(height=1),
            VSplit([Button("Revoke", revoke, width=10)], padding=1),
        ])

    def _detail_roles_actions(self, rid: Any) -> Any:
        cur = self._role_key(rid)
        info = f"Selected role: {cur}" if rid else "No role selected — “New role” still works."

        def rename() -> None:
            if not rid:
                return
            self.guard_write(lambda: self.ask_input(
                "Rename role", "New key:", cur,
                lambda key: key and self.run_write(
                    lambda: ops.rename_role(self.db, rid, key, key), "role renamed"),
            ))

        def delete() -> None:
            if not rid:
                return
            self.guard_write(lambda: self.confirm(
                f"DELETE role '{cur}'?\nCascades its permissions, assignments and OIDC mappings.",
                lambda: self.run_write(lambda: ops.delete_role(self.db, rid), "role deleted"),
                title="Delete role",
            ))

        buttons = VSplit(
            [Button("New…", self._new_role, width=9), Button("Rename", rename, width=10),
             Button("Delete", delete, width=10)],
            padding=1,
        )
        return HSplit([self._heading("Role actions"), Box(Label(info), padding=0), Window(height=1), buttons, Window()])

    def _new_role(self) -> None:
        self.guard_write(lambda: self.ask_input(
            "New role", "Role key (e.g. treasurer):", "",
            lambda key: key and self.run_write(
                lambda: ops.create_role(self.db, key, key), "role created"),
        ))

    # ------------------------------------------------------------------ OIDC mappings
    def _build_oidc(self) -> None:
        rows = ops.list_mappings(self.db)
        self._mappings = rows
        values = [
            (r["id"], f"{r['oidc_group']} → {r['role_key']}"
             + (f" @ {r['gremium']}" if r["gremium"] else " (global)"))
            for r in rows
        ]
        ctrl, focus = self._list_or_empty(values, self._selected.get("oidc"), fill=True)
        self._left_ctrl = ctrl
        new_btn = Button("New mapping…", lambda: self.guard_write(lambda: self._mapping_flow(None)), width=22)
        left = HSplit([new_btn, Window(height=1), ctrl])
        self._master_detail(left, focus, left_title=f"OIDC mappings ({len(rows)})")

    def _detail_oidc_actions(self, mid: Any) -> Any:
        row = next((m for m in self._mappings if m["id"] == mid), None)
        if row is not None:
            scope = f" @ {row['gremium']}" if row["gremium"] else " (global)"
            info = f"{row['oidc_group']} → {row['role_key']}{scope}"
        else:
            info = "No mapping selected — “New” still works."

        def edit() -> None:
            if row is not None:
                self.guard_write(lambda: self._mapping_flow(row))

        def delete() -> None:
            if not mid:
                return
            self.guard_write(lambda: self.confirm(
                "Delete this OIDC group-mapping?",
                lambda: self.run_write(lambda: ops.delete_mapping(self.db, mid), "mapping deleted"),
            ))

        buttons = VSplit(
            [Button("New…", lambda: self.guard_write(lambda: self._mapping_flow(None)), width=9),
             Button("Edit", edit, width=8), Button("Delete", delete, width=10)],
            padding=1,
        )
        return HSplit([self._heading("Mapping actions"), Box(Label(info), padding=0), Window(height=1), buttons, Window()])

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

    # ------------------------------------------------------------------ AUDIT (full width)
    def _build_audit(self) -> None:
        if not self._audit_rows:
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

        title = "Audit log" + (f" · action “{self._audit_action}”" if self._audit_action else "")
        buttons = VSplit(
            [Button("Load more", more, width=12), Button("Filter…", filt, width=10),
             Button("Reset", self._reset_audit, width=8)],
            padding=1,
        )
        body = Frame(HSplit([area, Window(height=1), buttons]), title=title)
        self._set_body(body, area)

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
        head = f"  {'#':>8}  {'WHEN (UTC)':<19}  {'ACTOR':<26}  {'ACTION':<24}  TARGET"
        sep = "  " + "─" * 96
        if not rows:
            return f"{head}\n{sep}\n  (no audit entries)"
        out = [head, sep]
        for r in rows:
            tgt = f"{r['target_type']}:{r['target_id']}" if r["target_type"] else "—"
            actor = (_fmt(r["actor"]) or "—")[:26]
            action = _fmt(r["action"])[:24]
            out.append(
                f"  {_fmt(r['id']):>8}  {_fmt(r['at'])[:19]:<19}  {actor:<26}  {action:<24}  {tgt}"
            )
            data = _fmt(r["data"])
            if data and data not in ("{}", "null"):
                out.append(f"            ↳ {data[:140]}")
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
