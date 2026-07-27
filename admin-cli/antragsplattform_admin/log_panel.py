"""The scrolling log: its model, hover and detail state, and render callbacks.

This module owns the log deque and the transient hover, pop-out and scroll state.
It produces the fragments the layout renders for the log, the completion menu and
the record pop-out. The log panel appends a domain row from `views` with a mouse
handler. That handler highlights the row on hover and pops out its detail on click.
"""

from __future__ import annotations

from collections import deque

from prompt_toolkit.application.current import get_app
from prompt_toolkit.completion import Completion
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType

from . import panels, views
from .models import LogEntry
from .protocols import AppContext, MouseHandler
from .theme import DETAIL_HIGHLIGHT, HOVER_HIGHLIGHT

# Visible rows of the completion menu. This matches the window height in the layout.
_COMPLETION_ROWS = 12


class LogPanel:
    """The log model plus the fragment callbacks that render it."""

    def __init__(self, context: AppContext) -> None:
        self._context = context
        self._log: deque[LogEntry] = deque(maxlen=5000)
        self._scroll = 0
        self._completion_scroll = 0
        self._hover: LogEntry | None = None
        self._detail: LogEntry | None = None

    def append(self, entry: LogEntry) -> None:
        """Append an entry and keep the scroll anchored when the user scrolled back."""
        self._log.append(entry)
        if self._scroll > 0:
            self._scroll = min(self._scroll + 1, len(self._log) - 1)
        self._context.invalidate()

    def append_record(self, row: views.Row) -> None:
        """Append a domain row and attach its hover and click handler to every fragment.

        A row without a detail view stays plain text. A day separator is one example.
        """
        line, detail, title = row
        if not detail:
            self.append(LogEntry(fragments=line))
            return
        entry = LogEntry(detail=detail, detail_title=title)
        handler = self._entry_mouse(entry)
        entry.fragments = [(style, text, handler) for style, text, *_ in line]
        self.append(entry)

    def pop_out(self, detail: StyleAndTextTuples, title: str) -> None:
        """Open the record pop-out directly, for commands such as `/user … show`."""
        self._detail = LogEntry(detail=detail, detail_title=title)
        self._hover = None
        self._context.invalidate()

    def clear(self) -> None:
        """Drop every log line and reset the scroll and the pop-out."""
        self._log.clear()
        self._scroll = 0
        self._hover = None
        self._detail = None
        self._context.invalidate()

    def _entry_mouse(self, entry: LogEntry) -> MouseHandler:
        def handler(mouse_event: MouseEvent) -> object:
            event_type = mouse_event.event_type
            if event_type == MouseEventType.MOUSE_MOVE:
                self.set_hover(entry)
            elif event_type == MouseEventType.MOUSE_UP:
                self._detail = entry
                self.set_hover(None)
                self._context.invalidate()
            elif event_type == MouseEventType.SCROLL_UP:
                self.scroll_log(3)
            elif event_type == MouseEventType.SCROLL_DOWN:
                self.scroll_log(-3)
            else:
                return NotImplemented
            return None

        return handler

    def set_hover(self, entry: LogEntry | None) -> None:
        """Set or clear the hovered entry and repaint only on a change."""
        if self._hover is not entry:
            self._hover = entry
            self._context.invalidate()

    def hover_clear(self, mouse_event: MouseEvent) -> object:
        """Clear the hover on move, close the pop-out on click, scroll on wheel.

        Plain log lines and the empty padding above them use this handler. The
        wheel then still scrolls while the cursor is over a line that is not a
        record.
        """
        event_type = mouse_event.event_type
        if event_type == MouseEventType.MOUSE_MOVE:
            self.set_hover(None)
            return None
        if event_type == MouseEventType.MOUSE_UP:
            self.close_detail()
            return None
        if event_type == MouseEventType.SCROLL_UP:
            self.scroll_log(3)
            return None
        if event_type == MouseEventType.SCROLL_DOWN:
            self.scroll_log(-3)
            return None
        return NotImplemented

    def detail_close_click(self, mouse_event: MouseEvent) -> object:
        """Close the pop-out when the user clicks its "esc to close" line."""
        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            self.close_detail()
            return None
        if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
            return None
        return NotImplemented

    def close_detail(self) -> None:
        """Dismiss the popped-out record panel when it is open."""
        if self._detail is not None:
            self._detail = None
            self._context.invalidate()

    def scroll_log(self, delta: int) -> None:
        """Scroll the log by a number of lines.

        Args:
            delta: Lines to scroll. A positive value moves toward older lines.
        """
        self._scroll = max(0, min(self._scroll + delta, max(0, len(self._log) - 1)))
        self._context.invalidate()

    def scroll_to_bottom(self) -> None:
        """Jump back to the newest line."""
        if self._scroll != 0:
            self._scroll = 0
            self._context.invalidate()

    def scrolled_up(self) -> bool:
        """Return True when the log is scrolled away from the newest line."""
        return self._scroll > 0

    def showing_detail(self) -> bool:
        return self._detail is not None

    def detail_title(self) -> str:
        return self._detail.detail_title if self._detail else ""

    def log_height(self) -> int:
        """Return the number of log lines that fit above the input and the status."""
        try:
            rows = get_app().output.get_size().rows
        except Exception:  # noqa: BLE001 — fall back when no app is running yet
            rows = 24
        buffer = self._context.buffer
        state = buffer.complete_state
        completions = (
            0 if state is None else min(_COMPLETION_ROWS, len(state.completions))
        )
        return max(1, rows - 2 - buffer.document.line_count - completions)

    def _term_columns(self) -> int:
        try:
            return get_app().output.get_size().columns
        except Exception:  # noqa: BLE001 — fall back when no app is running yet
            return 120

    def log_fragments(self) -> StyleAndTextTuples:
        entries = list(self._log)
        height = self.log_height()
        end = max(0, len(entries) - self._scroll)
        start = max(0, end - height)
        visible = entries[start:end]
        width = self._term_columns()
        fragments: StyleAndTextTuples = [
            ("", "\n", self.hover_clear) for _ in range(height - len(visible))
        ]
        for entry in visible:
            if entry is self._detail:
                fragments.extend(
                    views.highlight(entry.fragments, DETAIL_HIGHLIGHT, width)
                )
            elif entry is self._hover:
                fragments.extend(
                    views.highlight(entry.fragments, HOVER_HIGHLIGHT, width)
                )
            elif entry.detail is None:
                # Plain rows get the hover-clearing handler across the full width.
                # A stale hover highlight then never sticks.
                fragments.extend(
                    views.repaint(entry.fragments, width, handler=self.hover_clear)
                )
            else:
                fragments.extend(entry.fragments)
        return fragments

    def completion_fragments(self) -> StyleAndTextTuples:
        state = self._context.buffer.complete_state
        if state is None:
            self._completion_scroll = 0
            return []
        completions = list(state.completions)
        selected = state.complete_index
        rows = _COMPLETION_ROWS

        # Scroll only when the selected item leaves the visible window. The menu
        # can then hold more entries than fit, and the cursor stays on screen.
        if selected is not None:
            if selected < self._completion_scroll:
                self._completion_scroll = selected
            elif selected >= self._completion_scroll + rows:
                self._completion_scroll = selected - rows + 1
        self._completion_scroll = max(
            0, min(self._completion_scroll, max(0, len(completions) - rows))
        )

        start = self._completion_scroll
        visible = completions[start : start + rows]
        visible_selected = (
            selected - start
            if selected is not None and start <= selected < start + rows
            else None
        )
        return panels.completion_fragments(
            visible, visible_selected, self._completion_click, len(completions), start
        )

    def _completion_click(self, completion: Completion) -> MouseHandler:
        def handler(mouse_event: MouseEvent) -> object:
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                self._context.buffer.apply_completion(completion)
                self._context.invalidate()
                return None
            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.set_hover(None)
                return None
            return NotImplemented

        return handler

    def _consume(self, _mouse_event: MouseEvent) -> object:
        # Swallow events over the floating panel so it stays put and stays open.
        return None

    def detail_fragments(self) -> StyleAndTextTuples:
        return (
            panels.detail_fragments(self._detail, self._consume, self.detail_close_click)
            if self._detail
            else []
        )


__all__ = ["LogPanel"]
