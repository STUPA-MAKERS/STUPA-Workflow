"""Fragment builders for the floating panels and the completion menu.

Every builder is pure. It takes the data to show plus the mouse handlers to
attach, and returns prompt_toolkit fragments. The pop-out detail re-emits the
pre-rendered record view of an entry and adds a close hint. The selector and the
form renderer window their rows around the cursor.
"""

from __future__ import annotations

from collections.abc import Callable

from prompt_toolkit.completion import Completion
from prompt_toolkit.formatted_text import StyleAndTextTuples

from .models import Form, FormField, LogEntry, Selector
from .protocols import MouseHandler


def detail_fragments(
    entry: LogEntry, consume: MouseHandler, close: MouseHandler
) -> StyleAndTextTuples:
    """Build the popped-out record view: the pre-rendered detail plus a close hint.

    Args:
        entry: The clicked log entry. It must carry a detail view.
        consume: Handler attached to every fragment. A click inside the panel then
            keeps the panel open.
        close: Handler attached to the "esc to close" line. A click on that line
            also dismisses the panel.
    """
    if entry.detail is None:
        return []
    fragments: StyleAndTextTuples = [
        (style, text, consume) for style, text, *_ in entry.detail
    ]
    fragments.append(("class:select-hint", "\nesc to close", close))
    return fragments


def selector_fragments(
    selector: Selector, option_handler: Callable[[int], MouseHandler], rows: int
) -> StyleAndTextTuples:
    """Render a scrolled window of the selector around its cursor.

    The panel shows only `rows` options at once. The caller keeps
    ``selector.scroll`` on the cursor. The first or the last visible row gets a
    ``↑`` or a ``↓`` marker when more options lie off screen. The digit keys pick
    the visible rows.
    """
    options = selector.visible()
    start = selector.scroll
    total = len(options)
    window = options[start : start + rows]
    fragments: StyleAndTextTuples = []
    if selector.searchable:
        fragments.append(("class:select-key", "search: "))
        fragments.append(("class:select-active", f"{selector.query}▏\n"))
    for offset, (_value, label) in enumerate(window):
        index = start + offset
        active = index == selector.cursor
        handler = option_handler(index)
        if offset == 0 and start > 0:
            marker = "↑"
        elif offset == len(window) - 1 and start + len(window) < total:
            marker = "↓"
        else:
            marker = " "
        key = "  " if selector.searchable else f"{offset + 1}." if offset < 9 else "  "
        fragments.append(
            ("class:select-pointer", f"{marker} ❯ ", handler)
            if active
            else ("class:select-hint", f"{marker}   ", handler)
        )
        fragments.append(("class:select-key", f"{key} ", handler))
        fragments.append(
            ("class:select-active" if active else "", f"{label}\n", handler)
        )
    if not window:
        fragments.append(("class:select-hint", "  no matches\n"))
    hint = (
        "type to search · ↑/↓ · enter · esc"
        if selector.searchable
        else f"↑/↓ · {selector.cursor + 1}/{max(total, 1)} · enter · esc"
    )
    fragments.append(("class:select-hint", hint))
    return fragments


# Builds the mouse handler that cycles the field at an index by a step of ±1.
ArrowHandler = Callable[[int, int], MouseHandler]


def _form_value(field: FormField, active: bool) -> tuple[str, str]:
    """Return the ``(style, text)`` pair shown for the current value of a form row."""
    if field.kind == "bool":
        return (
            "class:on" if field.choice_index else "class:select-key",
            "on " if field.choice_index else "off",
        )
    if field.kind == "choice":
        return (
            "class:select-active" if active else "",
            field.choices[field.choice_index] if field.choices else "(none)",
        )
    caret = "▏" if active else ""
    return (
        "class:select-active" if active else "class:value",
        f"{field.text}{caret}",
    )


def _form_hint(field: FormField) -> str:
    """Return a short hint that tells what the focused form row accepts."""
    base = (
        "space/←/→"
        if field.kind == "bool"
        else "←/→"
        if field.kind == "choice"
        else "type to edit"
    )
    return f"{base}   {field.hint}" if field.hint else base


def form_fragments(
    form: Form,
    focus: Callable[[int], MouseHandler],
    arrow: ArrowHandler,
    rows: int,
) -> StyleAndTextTuples:
    """Render a form dialog: a scrolled window of field rows plus a key hint.

    The panel shows only `rows` fields at once. The caller keeps ``form.scroll``
    on the cursor. The first or the last visible row gets a ``↑`` or a ``↓`` marker
    when more fields lie off screen.
    """
    name_width = max((len(field.label) for field in form.fields), default=0)
    start = form.scroll
    total = len(form.fields)
    window = form.fields[start : start + rows]
    fragments: StyleAndTextTuples = []
    for offset, field in enumerate(window):
        index = start + offset
        active = index == form.cursor
        cyclable = field.kind in ("bool", "choice")
        focus_handler = focus(index)
        value_handler = arrow(index, 1) if cyclable else focus_handler
        if offset == 0 and start > 0:
            marker = "↑"
        elif offset == len(window) - 1 and start + len(window) < total:
            marker = "↓"
        else:
            marker = " "
        fragments.append(
            ("class:select-pointer", f"{marker} ❯ ", focus_handler)
            if active
            else ("class:select-hint", f"{marker}   ", focus_handler)
        )
        fragments.append(
            ("class:dim", f"{field.label:<{name_width}}  ", focus_handler)
        )
        value_style, value_text = _form_value(field, active)
        if active and cyclable:
            fragments.append(("class:select-hint", "◀ ", arrow(index, -1)))
            fragments.append((value_style, value_text, value_handler))
            fragments.append(("class:select-hint", " ▶", arrow(index, 1)))
        else:
            fragments.append((value_style, value_text, value_handler))
        if active:
            fragments.append(
                ("class:select-hint", f"   {_form_hint(field)}", focus_handler)
            )
        fragments.append(("", "\n", focus_handler))
    scrolled = total > rows
    position = f" · {form.cursor + 1}/{total}" if scrolled else ""
    fragments.append(
        (
            "class:select-hint",
            f"↑/↓ move{position} · ←/→ change · type · enter apply · esc",
        )
    )
    return fragments


def completion_fragments(
    completions: list[Completion],
    selected_index: int | None,
    click: Callable[[Completion], MouseHandler],
    total: int,
    start: int,
) -> StyleAndTextTuples:
    """Render a slice of the completion menu, scrolled when needed.

    The `completions` list is the visible window of `total` entries and starts at
    `start`. An edge row gets a ``↑`` or a ``↓`` marker when more entries lie off
    screen. The renderer reverses the selected entry. Every entry is clickable.
    """
    last = len(completions) - 1
    fragments: StyleAndTextTuples = []
    for index, completion in enumerate(completions):
        if index == 0 and start > 0:
            marker = "↑"
        elif index == last and start + len(completions) < total:
            marker = "↓"
        else:
            marker = " "
        fragments.append(
            (
                "class:comp-sel" if index == selected_index else "class:comp",
                f"{marker} {completion.text} ",
                click(completion),
            )
        )
        meta = completion.display_meta_text
        if meta:
            fragments.append(("class:select-hint", f" {meta}", click(completion)))
        fragments.append(("", "\n", click(completion)))
    return fragments


__all__ = [
    "detail_fragments",
    "selector_fragments",
    "form_fragments",
    "completion_fragments",
]
