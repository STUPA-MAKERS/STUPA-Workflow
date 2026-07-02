"""Assembly of the full-screen application layout.

A vertical stack of log, completion menu, input and status line, with the
popped-out record detail, the inline selector and the form dialog layered as
floats. The fragments and predicates all come from the orchestrator; this
module only wires them into prompt_toolkit containers.
"""

from __future__ import annotations

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Box, Frame

from .completion import CommandLexer
from .key_bindings import build_key_bindings
from .protocols import AppView
from .theme import STYLE


def _panel(
    fragments: object,
    title: object,
    visible: Condition,
    min_width: int,
    max_width: int,
    max_height: int,
) -> ConditionalContainer:
    """A bordered, self-sizing panel shown only while *visible*."""
    window = Window(
        FormattedTextControl(fragments),  # pyright: ignore[reportArgumentType]
        width=Dimension(min=min_width, max=max_width),
        height=Dimension(max=max_height),
        dont_extend_height=True,
        wrap_lines=True,
    )
    # One column of horizontal breathing room inside the border.
    padded = Box(window, padding=0, padding_left=1, padding_right=1)
    return ConditionalContainer(
        Frame(padded, title=title),  # pyright: ignore[reportArgumentType]
        filter=visible,
    )


def build_app(cli: AppView) -> Application:
    """Build the full-screen, mouse-aware application around *cli*."""
    logs, form_panel = cli.logs, cli.form_panel
    log_window = Window(
        FormattedTextControl(logs.log_fragments, focusable=False),
        wrap_lines=False,
    )
    completion_window = Window(
        FormattedTextControl(logs.completion_fragments),
        height=Dimension(max=12),
        dont_extend_height=True,
        style="class:comp",
    )
    input_window = Window(
        BufferControl(buffer=cli.buffer, lexer=CommandLexer()),
        height=Dimension(min=1),
        dont_extend_height=True,
        wrap_lines=True,
        get_line_prefix=cli.line_prefix,
    )
    status_window = Window(
        FormattedTextControl(cli.toolbar),
        height=1,
        style="class:bottom-toolbar",
    )
    body = FloatContainer(
        content=HSplit([log_window, completion_window, input_window, status_window]),
        floats=[
            Float(
                content=_panel(
                    logs.detail_fragments,
                    logs.detail_title,
                    Condition(logs.showing_detail),
                    min_width=44,
                    max_width=96,
                    max_height=30,
                )
            ),
            Float(
                content=_panel(
                    cli.selector_fragments,
                    cli.selector_title,
                    Condition(cli.showing_selector),
                    min_width=28,
                    max_width=76,
                    max_height=20,
                )
            ),
            Float(
                content=_panel(
                    form_panel.fragments,
                    form_panel.title,
                    Condition(form_panel.showing),
                    min_width=44,
                    max_width=76,
                    max_height=20,
                )
            ),
            Float(
                bottom=1,
                right=3,
                content=ConditionalContainer(
                    Window(
                        FormattedTextControl(cli.scroll_button_fragments),
                        height=1,
                        dont_extend_width=True,
                    ),
                    filter=Condition(logs.scrolled_up),
                ),
            ),
        ],
    )
    return Application(
        layout=Layout(body, focused_element=input_window),
        key_bindings=build_key_bindings(cli),
        style=STYLE,
        full_screen=True,
        mouse_support=True,
    )


__all__ = ["build_app"]
