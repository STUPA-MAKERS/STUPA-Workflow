"""Plain data the UI carries around: log entries, the selector and form dialogs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from prompt_toolkit.formatted_text import StyleAndTextTuples

# ``(value, label)`` pairs offered by a selector. Defined here (a package leaf)
# so protocols can import it without a models↔protocols cycle.
Choices = list[tuple[str, str]]


@dataclass
class LogEntry:
    """One rendered line in the scrolling log.

    Info, error and prompt-echo lines are pure text. A domain row (user, role,
    mapping, audit entry) additionally carries pre-rendered *detail* fragments
    so the UI can highlight it on hover and pop out the full record on click.

    Attributes:
        fragments: The pre-rendered line, newline included.
        detail: The popped-out record view, or ``None`` for plain text rows.
        detail_title: Heading of the pop-out panel (e.g. ``user`` / ``audit #4812``).
    """

    fragments: StyleAndTextTuples = field(default_factory=list)
    detail: StyleAndTextTuples | None = None
    detail_title: str = ""


@dataclass
class Selector:
    """An in-app single-choice picker awaiting a decision.

    Attributes:
        title: Heading shown above the options.
        values: ``(key, label)`` options to choose from.
        on_choose: Called with the chosen key, or ``None`` when cancelled.
        cursor: Index of the currently-highlighted option (into :meth:`visible`).
        scroll: Index of the first visible option (into :meth:`visible`).
        query: Live search text; narrows the options when :attr:`searchable`.
        searchable: Whether typing filters the options (for long lists).
    """

    title: str
    values: Choices
    on_choose: Callable[[str | None], None]
    cursor: int = 0
    scroll: int = 0
    query: str = ""
    searchable: bool = False

    def visible(self) -> Choices:
        """The options matching the current query (all of them when empty)."""
        if not self.query:
            return self.values
        needle = self.query.lower()
        return [
            (value, label)
            for value, label in self.values
            if needle in label.lower() or needle in value.lower()
        ]


@dataclass
class FormField:
    """One editable row in a form dialog (mapping editor, permission set, …).

    Attributes:
        key: Stable identifier used when reading the value back out.
        label: Heading shown for the row.
        kind: ``text`` (free text), ``bool`` (on/off) or ``choice`` (one of ``choices``).
        text: The edit buffer, for ``text`` fields.
        choice_index: The selected option, for ``bool``/``choice`` fields.
        choices: The option labels, for ``choice`` fields.
        hint: Extra hint shown while the row is focused (e.g. ``⚠ human-only``).
    """

    key: str
    label: str
    kind: str  # "text" | "bool" | "choice"
    text: str = ""
    choice_index: int = 0
    choices: list[str] = field(default_factory=list)
    hint: str = ""


@dataclass
class Form:
    """A generic field-by-field dialog awaiting entry.

    Attributes:
        title: Heading shown on the panel frame.
        fields: The editable rows, in display order.
        on_submit: Called with the form when the user presses Enter.
        cursor: Index of the currently-focused row.
        scroll: Index of the first visible row (long forms scroll).
    """

    title: str
    fields: list[FormField]
    on_submit: Callable[[Form], None]
    cursor: int = 0
    scroll: int = 0

    def by_key(self) -> dict[str, FormField]:
        """The fields indexed by their stable :attr:`FormField.key`."""
        return {field.key: field for field in self.fields}


__all__ = ["Choices", "LogEntry", "Selector", "FormField", "Form"]
