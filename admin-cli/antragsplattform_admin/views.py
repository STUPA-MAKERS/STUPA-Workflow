"""Rendering of domain rows into log fragments.

Each list command's rows become aligned, coloured log lines; every row also gets
a pre-rendered pop-out detail view (shown on click). All pure text-in →
fragments-out; mouse handlers are attached by the log panel when the entries are
appended. Works on both DB backends: values may be native (psycopg) or strings
(docker/psql CSV), so everything is normalised through :func:`fmt` first.

Row = ``(line fragments, detail fragments, detail title)``.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from prompt_toolkit.formatted_text import StyleAndTextTuples

from .protocols import MouseHandler

# One rendered row: the log line, its pop-out detail, and the pop-out title.
Row = tuple[StyleAndTextTuples, StyleAndTextTuples, str]


def fmt(value: Any) -> str:
    """Normalise a DB value (native or CSV string) to display text."""
    return "" if value is None else str(value)


def truthy(value: Any) -> bool:
    """Interpret a boolean DB value from either backend."""
    return value is True or str(value).lower() in ("true", "t", "1")


def clip(text: str, width: int) -> str:
    """Clip *text* to *width*, marking the cut with an ellipsis."""
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def short_id(value: Any) -> str:
    """A recognisable 8-char prefix of a UUID-ish id (full value in the detail)."""
    text = fmt(value)
    return text[:8] + "…" if len(text) > 9 else text


def dt_parts(value: Any) -> tuple[str, str]:
    """Split a timestamp (datetime or ISO-ish string) into (date, HH:MM:SS)."""
    if isinstance(value, datetime):
        return value.date().isoformat(), value.strftime("%H:%M:%S")
    text = fmt(value)
    if len(text) >= 19:
        return text[:10], text[11:19]
    return text, ""


def day_heading(date_str: str) -> str:
    """``Mon 2026-06-30`` when the date parses, else the raw string."""
    try:
        parsed = date.fromisoformat(date_str)
    except ValueError:
        return date_str
    return parsed.strftime("%a %Y-%m-%d")


def separator(label: str, width: int = 72) -> StyleAndTextTuples:
    """A ``── label ───…`` day/section break line."""
    bar = "─" * max(0, width - len(label) - 4)
    return [("class:sep", "── "), ("class:dim", label), ("class:sep", f" {bar}\n")]


def _kv(rows: list[tuple[str, str, str]]) -> StyleAndTextTuples:
    """Aligned ``name  value`` lines for a detail pop-out: (name, style, value)."""
    if not rows:
        return []
    width = max(len(name) for name, _style, _value in rows)
    fragments: StyleAndTextTuples = []
    for name, style, value in rows:
        fragments.append(("class:dim", f"{name:<{width}}  "))
        fragments.append((style, f"{value}\n"))
    return fragments


# --------------------------------------------------------------------------------- users
def user_name(row: dict[str, Any]) -> str:
    """The best display handle for a principal row."""
    return fmt(row.get("email")) or fmt(row.get("display_name")) or fmt(row.get("sub"))


def _user_detail(row: dict[str, Any], assignments: str) -> StyleAndTextTuples:
    active = truthy(row.get("active"))
    fragments: StyleAndTextTuples = [
        ("class:detail-accent", f"{user_name(row)}\n\n"),
    ]
    fragments += _kv(
        [
            ("sub", "class:value", fmt(row.get("sub")) or "—"),
            ("id", "class:id", fmt(row.get("id"))),
            ("display", "class:value", fmt(row.get("display_name")) or "—"),
            ("email", "class:value", fmt(row.get("email")) or "—"),
            (
                "active",
                "class:active" if active else "class:off",
                "yes" if active else "no",
            ),
            ("last login", "class:value", fmt(row.get("last_login"))[:19] or "never"),
            ("roles", "class:value", assignments or "—"),
        ]
    )
    return fragments


def user_rows(rows: list[dict[str, Any]]) -> list[Row]:
    """One aligned line per principal: active dot, name, roles, last login."""
    if not rows:
        return []
    name_width = min(40, max(len(clip(user_name(r), 40)) for r in rows))
    role_width = min(38, max(len(clip(fmt(r.get("roles")) or "—", 38)) for r in rows))
    out: list[Row] = []
    for row in rows:
        active = truthy(row.get("active"))
        name = clip(user_name(row), 40)
        roles = clip(fmt(row.get("roles")) or "—", 38)
        last = fmt(row.get("last_login"))[:16] or "never"
        line: StyleAndTextTuples = [
            ("class:active" if active else "class:inactive", "  ● " if active else "  ○ "),
            ("class:email", f"{name:<{name_width}}  "),
            ("class:dim", f"{roles:<{role_width}}  "),
            ("class:time", f"{last}\n"),
        ]
        out.append((line, _user_detail(row, fmt(row.get("roles"))), "user"))
    return out


# --------------------------------------------------------------------------------- roles
def role_rows(rows: list[dict[str, Any]]) -> list[Row]:
    """One line per role: key, permission count, assignment count."""
    if not rows:
        return []
    key_width = min(28, max(len(clip(fmt(r.get("key")), 28)) for r in rows))
    out: list[Row] = []
    for row in rows:
        key = clip(fmt(row.get("key")), 28)
        perms = fmt(row.get("perms")) or "0"
        assigned = fmt(row.get("assignments")) or "0"
        line: StyleAndTextTuples = [
            ("", "  "),
            ("class:value", f"{key:<{key_width}}  "),
            ("class:dim", f"{perms:>3} perms · {assigned:>3} assigned\n"),
        ]
        detail: StyleAndTextTuples = [
            ("class:detail-accent", f"{fmt(row.get('key'))}\n\n"),
        ]
        detail += _kv(
            [
                ("id", "class:id", fmt(row.get("id"))),
                ("permissions", "class:value", perms),
                ("assignments", "class:value", assigned),
            ]
        )
        out.append((line, detail, "role"))
    return out


def role_detail(
    key: str, permissions: list[str], assignees: list[str]
) -> StyleAndTextTuples:
    """The full pop-out for one role: its permission set and its holders."""
    fragments: StyleAndTextTuples = [("class:detail-accent", f"{key}\n\n")]
    fragments.append(("class:dim", f"permissions ({len(permissions)})\n"))
    for perm in permissions or ["—"]:
        fragments.append(("class:value", f"  {perm}\n"))
    fragments.append(("class:dim", f"\nassigned to ({len(assignees)})\n"))
    for assignee in assignees or ["—"]:
        fragments.append(("class:value", f"  {assignee}\n"))
    return fragments


# ----------------------------------------------------------------------- OIDC mappings
def mapping_label(row: dict[str, Any]) -> str:
    scope = fmt(row.get("gremium"))
    return f"{fmt(row.get('oidc_group'))} → {fmt(row.get('role_key'))}" + (
        f" @ {scope}" if scope else " (global)"
    )


def mapping_rows(rows: list[dict[str, Any]]) -> list[Row]:
    """One line per OIDC group-mapping: group → role @ scope."""
    if not rows:
        return []
    group_width = min(30, max(len(clip(fmt(r.get("oidc_group")), 30)) for r in rows))
    out: list[Row] = []
    for row in rows:
        scope = fmt(row.get("gremium"))
        line: StyleAndTextTuples = [
            ("", "  "),
            ("class:value", f"{clip(fmt(row.get('oidc_group')), 30):<{group_width}}"),
            ("class:dim", "  →  "),
            ("class:email", fmt(row.get("role_key"))),
            ("class:dim", f"  @ {scope}\n" if scope else "  (global)\n"),
        ]
        detail: StyleAndTextTuples = [
            ("class:detail-accent", f"{mapping_label(row)}\n\n"),
        ]
        detail += _kv(
            [
                ("id", "class:id", fmt(row.get("id"))),
                ("OIDC group", "class:value", fmt(row.get("oidc_group"))),
                ("role", "class:value", fmt(row.get("role_key"))),
                ("scope", "class:value", scope or "(global)"),
            ]
        )
        out.append((line, detail, "mapping"))
    return out


# --------------------------------------------------------------------------------- audit
# Action-prefix → style class; first match wins, checked in order.
_ACTION_STYLES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("delete", "remove", "revoke", "erasure"), "class:act-delete"),
    (("login", "logout", "auth", "token", "session"), "class:act-auth"),
    (("status", "transition"), "class:act-status"),
    (
        ("budget", "expense", "allocation", "transfer", "fiscal", "invoice", "booking"),
        "class:act-budget",
    ),
    (("config", "site", "flow", "form", "role", "mapping", "webhook"), "class:act-config"),
    (("pii", "privacy", "anonym"), "class:act-privacy"),
    (("vote", "ballot", "delegation"), "class:act-vote"),
)


def action_style(action: str) -> str:
    """The colour class for an audit action, by keyword."""
    lowered = action.lower()
    for keywords, style in _ACTION_STYLES:
        if any(keyword in lowered for keyword in keywords):
            return style
    return "class:act-plain"


def _pretty_data(raw: Any) -> str:
    """Pretty-print the audit ``data`` JSON; fall back to the raw text."""
    text = fmt(raw)
    if not text or text in ("{}", "null"):
        return ""
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False, sort_keys=True)
    except (ValueError, TypeError):
        return text


def audit_actor(row: dict[str, Any]) -> str:
    """The resolved actor handle: email/display name, else the raw sub, else system."""
    return (
        fmt(row.get("actor_email"))
        or fmt(row.get("actor_name"))
        or fmt(row.get("actor"))
        or "system"
    )


def _audit_detail(row: dict[str, Any]) -> StyleAndTextTuples:
    date_str, time_str = dt_parts(row.get("at"))
    target_type = fmt(row.get("target_type"))
    target = (
        f"{target_type}:{fmt(row.get('target_id'))}" if target_type else "—"
    )
    fragments: StyleAndTextTuples = [
        ("class:detail-accent", f"#{fmt(row.get('id'))}"),
        ("class:time", f"   {date_str} {time_str} UTC\n\n"),
    ]
    fragments += _kv(
        [
            ("actor", "class:email", audit_actor(row)),
            ("sub", "class:id", fmt(row.get("actor")) or "—"),
            ("action", action_style(fmt(row.get("action"))), fmt(row.get("action"))),
            ("target", "class:value", target),
        ]
    )
    data = _pretty_data(row.get("data"))
    if data:
        fragments.append(("class:dim", "\ndata\n"))
        for line in data.splitlines():
            fragments.append(("class:value", f"  {line}\n"))
    return fragments


def audit_rows(rows: list[dict[str, Any]], previous_date: str = "") -> list[Row]:
    """Audit lines, newest first, with a day-break separator between dates.

    Day-break rows carry no detail (empty list) and are appended as plain,
    non-clickable lines by the log panel. *previous_date* threads the last
    rendered date across pages so /more does not repeat the day heading.
    """
    out: list[Row] = []
    actor_width = min(
        26, max((len(clip(audit_actor(r), 26)) for r in rows), default=0)
    )
    action_width = min(
        24, max((len(clip(fmt(r.get("action")), 24)) for r in rows), default=0)
    )
    for row in rows:
        date_str, time_str = dt_parts(row.get("at"))
        if date_str != previous_date:
            out.append((separator(day_heading(date_str)), [], ""))
            previous_date = date_str
        action = fmt(row.get("action"))
        target_type = fmt(row.get("target_type"))
        target = f"{target_type}:{short_id(row.get('target_id'))}" if target_type else "—"
        data_text = fmt(row.get("data"))
        has_data = bool(data_text) and data_text not in ("{}", "null")
        line: StyleAndTextTuples = [
            ("class:time", f"  {time_str}  "),
            ("class:id", f"#{fmt(row.get('id')):>7}  "),
            ("class:email", f"{clip(audit_actor(row), 26):<{actor_width}}  "),
            (action_style(action), f"{clip(action, 24):<{action_width}}  "),
            ("class:dim", target),
        ]
        if has_data:
            line.append(("class:sep", "  ↳ "))
            line.append(("class:dim", clip(data_text, 44)))
        line.append(("", "\n"))
        out.append((line, _audit_detail(row), f"audit #{fmt(row.get('id'))}"))
    return out


# --------------------------------------------------------------------------- row repaint
def repaint(
    fragments: StyleAndTextTuples,
    width: int,
    *,
    background: str | None = None,
    handler: MouseHandler | None = None,
) -> StyleAndTextTuples:
    """Re-emit a rendered row, padded with spaces to *width*.

    With *background* set, every fragment (and the pad) is repainted over it,
    keeping per-fragment foreground styles and mouse handlers — the hover and
    detail highlight. With *handler* set, it fills in for fragments that carry
    no handler of their own and is attached to the pad and the trailing newline
    — plain-text rows, whose full width must clear a stale hover highlight. A
    fragment's own handler always wins (e.g. the clickable ``/more`` link).
    """
    first = fragments[0] if fragments else None
    pad_handler = handler or (first[2] if first and len(first) == 3 else None)
    out: StyleAndTextTuples = []
    length = 0
    for fragment in fragments:
        style, text = fragment[0], fragment[1]
        frag_handler = fragment[2] if len(fragment) == 3 else None
        if text.endswith("\n"):
            text = text[:-1]
        if not text:
            continue
        styled = f"{style} bg:{background}" if background else style
        effective = frag_handler or handler
        out.append((styled, text, effective) if effective else (styled, text))
        length += len(text)
    pad = max(0, width - length)
    if pad:
        spaces = " " * pad
        pad_style = f"bg:{background}" if background else ""
        out.append(
            (pad_style, spaces, pad_handler) if pad_handler else (pad_style, spaces)
        )
    out.append(("", "\n", handler) if handler else ("", "\n"))
    return out


def highlight(
    fragments: StyleAndTextTuples, background: str, width: int
) -> StyleAndTextTuples:
    """Repaint *fragments* over *background*, padded to *width*."""
    return repaint(fragments, width, background=background)


__all__ = [
    "Row",
    "fmt",
    "truthy",
    "clip",
    "short_id",
    "dt_parts",
    "day_heading",
    "separator",
    "user_name",
    "user_rows",
    "role_rows",
    "role_detail",
    "mapping_label",
    "mapping_rows",
    "audit_actor",
    "audit_rows",
    "action_style",
    "repaint",
    "highlight",
]
