"""A reusable field-by-field dialog engine (mapping editor, permission set, …).

Owns the open :class:`Form`, drives editing (keyboard and mouse) and the
scrolled render, and calls the form's ``on_submit`` on Enter. Callers build a
:class:`Form` — its fields and submit callback — and open it through
:meth:`~antragsplattform_admin.protocols.AppView.open_form`; this component
knows nothing about what any particular form means.
"""

from __future__ import annotations

from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType

from . import panels
from .models import Form
from .protocols import AppContext, MouseHandler

# Fields shown at once in a form panel; longer forms (e.g. /role … perms) scroll.
_FORM_ROWS = 14


class FormController:
    """Holds the open form and drives its editing and rendering."""

    def __init__(self, context: AppContext) -> None:
        self._context = context
        self._form: Form | None = None

    def open(self, form: Form) -> None:
        """Show *form*, replacing any open one."""
        self._form = form
        self._context.invalidate()

    def showing(self) -> bool:
        return self._form is not None

    def title(self) -> str:
        return self._form.title if self._form else ""

    def fragments(self) -> StyleAndTextTuples:
        form = self._form
        if form is None:
            return []
        cursor = form.cursor
        if cursor < form.scroll:
            form.scroll = cursor
        elif cursor >= form.scroll + _FORM_ROWS:
            form.scroll = cursor - _FORM_ROWS + 1
        form.scroll = max(0, min(form.scroll, max(0, len(form.fields) - _FORM_ROWS)))
        return panels.form_fragments(form, self._focus, self._arrow, _FORM_ROWS)

    def cancel(self) -> None:
        """Dismiss the form without submitting."""
        if self._form is not None:
            self._form = None
            self._context.invalidate()

    def submit(self) -> None:
        """Fire the form's ``on_submit`` and close it.

        Guarded like every other command entry point: a failing submit callback
        (e.g. a duplicate-key DB error) lands in the log, not on the screen as
        a traceback.
        """
        form = self._form
        if form is None:
            return
        self._form = None
        self._context.invalidate()
        try:
            form.on_submit(form)
        except Exception as error:  # noqa: BLE001 — a submit must never kill the UI
            self._context.error(f"{type(error).__name__}: {error}")

    def move(self, delta: int) -> None:
        """Move the field cursor by *delta*, wrapping around."""
        form = self._form
        if form is None or not form.fields:
            return
        form.cursor = (form.cursor + delta) % len(form.fields)
        self._context.invalidate()

    def change(self, delta: int) -> None:
        """Cycle the focused bool/choice field; ignored for text fields."""
        form = self._form
        if form is None or not form.fields:
            return
        field = form.fields[form.cursor]
        if field.kind == "bool":
            field.choice_index ^= 1
        elif field.kind == "choice" and field.choices:
            field.choice_index = (field.choice_index + delta) % len(field.choices)
        else:
            return
        self._context.invalidate()

    def type_char(self, text: str) -> None:
        """Append typed *text* to the focused text field; space toggles bools."""
        form = self._form
        if form is None or not form.fields:
            return
        field = form.fields[form.cursor]
        if field.kind == "bool" and text == " ":
            field.choice_index ^= 1
            self._context.invalidate()
            return
        if field.kind != "text":
            return
        if len(text) == 1 and text.isprintable():
            field.text += text
            self._context.invalidate()

    def backspace(self) -> None:
        """Delete the last character of the focused text field."""
        form = self._form
        if form is None or not form.fields:
            return
        field = form.fields[form.cursor]
        if field.kind != "text":
            return
        field.text = field.text[:-1]
        self._context.invalidate()

    def _focus(self, index: int) -> MouseHandler:
        def handler(mouse_event: MouseEvent) -> object:
            event_type = mouse_event.event_type
            if event_type == MouseEventType.MOUSE_UP:
                if self._form is not None and index < len(self._form.fields):
                    self._form.cursor = index
                    self._context.invalidate()
                return None
            if event_type == MouseEventType.SCROLL_UP:
                self.move(-1)
                return None
            if event_type == MouseEventType.SCROLL_DOWN:
                self.move(1)
                return None
            if event_type == MouseEventType.MOUSE_MOVE:
                return None
            return NotImplemented

        return handler

    def _arrow(self, index: int, delta: int) -> MouseHandler:
        def handler(mouse_event: MouseEvent) -> object:
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                if self._form is not None and index < len(self._form.fields):
                    self._form.cursor = index
                    self.change(delta)
                return None
            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                return None
            return NotImplemented

        return handler


__all__ = ["FormController"]
