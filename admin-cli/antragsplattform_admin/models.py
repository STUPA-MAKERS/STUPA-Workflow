"""Plain data the UI carries around: log entries, the selector and form dialogs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from prompt_toolkit.formatted_text import StyleAndTextTuples

# ``(value, label)`` pairs that a selector offers. This module is a package leaf,
# so protocols can import the type without a models/protocols import cycle.
Choices = list[tuple[str, str]]


@dataclass
class LogEntry:
    """One rendered line in the scrolling log.

    Info, error and prompt-echo lines are pure text. A domain row also carries
    pre-rendered detail fragments. A domain row is a user, a role, a mapping or an
    audit entry. The UI uses the detail fragments to highlight the row on hover and
    to pop out the full record on click.

    Attributes:
        fragments: The pre-rendered line, newline included.
        detail: The popped-out record view. ``None`` marks a plain text row.
        detail_title: Heading of the pop-out panel, for example ``user`` or
            ``audit #4812``.
    """

    fragments: StyleAndTextTuples = field(default_factory=list)
    detail: StyleAndTextTuples | None = None
    detail_title: str = ""


@dataclass
class Selector:
    """An in-app single-choice picker that waits for a decision.

    Attributes:
        title: Heading shown above the options.
        values: The ``(key, label)`` options to choose from.
        on_choose: Called with the chosen key, or with ``None`` on cancel.
        cursor: Index of the highlighted option, into `visible`.
        scroll: Index of the first visible option, into `visible`.
        query: Live search text. It narrows the options when `searchable` is set.
        searchable: Set this to filter the options as the user types. Use it for
            long lists.
    """

    title: str
    values: Choices
    on_choose: Callable[[str | None], None]
    cursor: int = 0
    scroll: int = 0
    query: str = ""
    searchable: bool = False

    def visible(self) -> Choices:
        """Return the options that match the query, or all when the query is empty."""
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
    """One editable row in a form dialog, such as the mapping or permission editor.

    Attributes:
        key: Stable identifier that the caller uses to read the value back out.
        label: Heading shown for the row.
        kind: ``text`` for free text, ``bool`` for on/off, or ``choice`` for one of
            ``choices``.
        text: The edit buffer, for a ``text`` field.
        choice_index: The selected option, for a ``bool`` or ``choice`` field.
        choices: The option labels, for a ``choice`` field.
        hint: Extra hint shown while the row has the focus, for example
            ``⚠ human-only``.
    """

    key: str
    label: str
    kind: str
    text: str = ""
    choice_index: int = 0
    choices: list[str] = field(default_factory=list)
    hint: str = ""


@dataclass
class Form:
    """A generic field-by-field dialog that waits for entry.

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
        """Return the fields indexed by their stable `FormField.key`."""
        return {field.key: field for field in self.fields}


__all__ = ["Choices", "LogEntry", "Selector", "FormField", "Form"]
