"""Command completion and the input lexer.

`CommandCompleter` prefix-matches the raw `/token`, so `/au` offers `/audit`. Past the
command word it asks the orchestrator for the argument options: user emails, role keys,
actions and audit filter keys. `CommandLexer` paints the leading slash-command coral as
you type it.
"""

from __future__ import annotations

from collections.abc import Callable

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.lexers import Lexer

from .commands import BASE_COMMANDS
from .protocols import CompleterHost


class CommandLexer(Lexer):
    """Paints the leading slash-command of the input line."""

    def lex_document(self, document: Document) -> Callable[[int], StyleAndTextTuples]:
        def get_line(lineno: int) -> StyleAndTextTuples:
            line = document.lines[lineno]
            stripped = line.lstrip()
            if lineno != 0 or not stripped.startswith("/"):
                return [("", line)]
            lead = len(line) - len(stripped)
            command, separator, tail = stripped.partition(" ")
            fragments: StyleAndTextTuples = []
            if lead:
                fragments.append(("", line[:lead]))
            fragments.append(("class:command", command))
            if separator:
                fragments.append(("", separator + tail))
            return fragments

        return get_line


class CommandCompleter(Completer):
    """Prefix-completes slash-commands and their arguments.

    Unlike `NestedCompleter`, this completer matches the raw token, the `/` included.
    A partially typed command therefore completes, not only the empty `/`.
    """

    def __init__(self, host: CompleterHost) -> None:
        self.host = host

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> list[Completion]:
        text = document.text_before_cursor
        if "\n" in text or not text.lstrip().startswith("/"):
            return []
        parts = text.lstrip().split(" ")
        current = parts[-1]
        if len(parts) == 1:
            return [
                Completion(name, start_position=-len(current), display_meta=meta)
                for name, meta in BASE_COMMANDS.items()
                if name.startswith(current)
            ]
        options = self.host.argument_options(parts)
        return [
            Completion(option, start_position=-len(current))
            for option in options
            if option.lower().startswith(current.lower())
        ]


__all__ = ["CommandLexer", "CommandCompleter"]
