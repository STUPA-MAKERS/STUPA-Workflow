"""Key bindings for the full-screen UI.

While a selector or form is open its navigation keys take over and everything
else is swallowed. Otherwise Enter submits the command line, Tab completes,
PgUp/PgDn scroll the log, and Esc closes the popped-out record. All actions are
delegated to the orchestrator.
"""

from __future__ import annotations

from prompt_toolkit.filters import Condition, Filter
from prompt_toolkit.key_binding import KeyBindings, KeyBindingsBase, merge_key_bindings
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys

from .protocols import AppView, EditorPanelView


def _add_editor_bindings(
    bindings: KeyBindings,
    condition: Filter,
    panel: EditorPanelView,
) -> None:
    """Wire the field-editor keys of the form dialog.

    Arrows move between fields (``↑/↓``) or cycle a value (``←/→``), printable
    keys and backspace edit the focused text field, ``enter`` submits and
    ``escape`` cancels — all only while *condition* holds.
    """

    @bindings.add("up", filter=condition, eager=True)
    @bindings.add("c-p", filter=condition, eager=True)
    def _(_event: KeyPressEvent) -> None:
        panel.move(-1)

    @bindings.add("down", filter=condition, eager=True)
    @bindings.add("c-n", filter=condition, eager=True)
    def _(_event: KeyPressEvent) -> None:
        panel.move(1)

    @bindings.add("left", filter=condition, eager=True)
    def _(_event: KeyPressEvent) -> None:
        panel.change(-1)

    @bindings.add("right", filter=condition, eager=True)
    def _(_event: KeyPressEvent) -> None:
        panel.change(1)

    @bindings.add("backspace", filter=condition, eager=True)
    def _(_event: KeyPressEvent) -> None:
        panel.backspace()

    @bindings.add("enter", filter=condition, eager=True)
    def _(_event: KeyPressEvent) -> None:
        panel.submit()

    @bindings.add("escape", filter=condition, eager=True)
    def _(_event: KeyPressEvent) -> None:
        panel.cancel()

    # Not eager: an eager wildcard would also swallow the mouse-event key, so the
    # specific mouse binding could never dispatch clicks/scrolls to the panel.
    @bindings.add(Keys.Any, filter=condition)
    def _(event: KeyPressEvent) -> None:
        panel.type_char(event.data)


def build_key_bindings(cli: AppView) -> KeyBindingsBase:
    """Build the merged key bindings driving *cli*."""
    bindings = KeyBindings()
    logs, form_panel = cli.logs, cli.form_panel
    selecting = Condition(cli.showing_selector)
    searchable = Condition(cli.selector_searchable)
    plain_selecting = selecting & ~searchable
    search_selecting = selecting & searchable
    in_form = Condition(form_panel.showing)
    idle = Condition(
        lambda: not cli.showing_selector() and not form_panel.showing()
    )
    detail_open = Condition(
        lambda: logs.showing_detail()
        and not cli.showing_selector()
        and not form_panel.showing()
    )

    @bindings.add("up", filter=selecting, eager=True)
    @bindings.add("c-p", filter=selecting, eager=True)
    def _(_event: KeyPressEvent) -> None:
        cli.selector_move(-1)

    @bindings.add("down", filter=selecting, eager=True)
    @bindings.add("c-n", filter=selecting, eager=True)
    def _(_event: KeyPressEvent) -> None:
        cli.selector_move(1)

    @bindings.add("enter", filter=selecting, eager=True)
    def _(_event: KeyPressEvent) -> None:
        cli.selector_pick()

    @bindings.add("escape", filter=selecting, eager=True)
    def _(_event: KeyPressEvent) -> None:
        cli.selector_cancel()

    for digit in range(1, 10):

        @bindings.add(str(digit), filter=plain_selecting, eager=True)
        def _(_event: KeyPressEvent, choice: int = digit - 1) -> None:
            cli.selector_pick_visible(choice)

    @bindings.add("backspace", filter=search_selecting, eager=True)
    def _(_event: KeyPressEvent) -> None:
        cli.selector_backspace()

    # Not eager (see _add_editor_bindings): let the mouse-event key fall through
    # to the mouse binding so the selector list stays clickable and scrollable.
    @bindings.add(Keys.Any, filter=search_selecting)
    def _(event: KeyPressEvent) -> None:
        cli.selector_type(event.data)

    @bindings.add(Keys.Any, filter=plain_selecting)
    def _(_event: KeyPressEvent) -> None:
        return

    _add_editor_bindings(bindings, in_form, form_panel)

    @bindings.add("escape", filter=detail_open, eager=True)
    def _(_event: KeyPressEvent) -> None:
        logs.close_detail()

    @bindings.add("enter", filter=idle)
    def _(event: KeyPressEvent) -> None:
        event.current_buffer.validate_and_handle()

    @bindings.add("tab", filter=idle)
    def _(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if buffer.complete_state:
            buffer.complete_next()
        else:
            buffer.start_completion(select_first=True)

    @bindings.add("s-tab", filter=idle)
    def _(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if buffer.complete_state:
            buffer.complete_previous()

    @bindings.add("pageup")
    def _(_event: KeyPressEvent) -> None:
        logs.scroll_log(logs.log_height() - 1)

    @bindings.add("pagedown")
    def _(_event: KeyPressEvent) -> None:
        logs.scroll_log(-(logs.log_height() - 1))

    @bindings.add("c-c")
    def _(event: KeyPressEvent) -> None:
        if cli.showing_selector():
            cli.selector_cancel()
        elif form_panel.showing():
            form_panel.cancel()
        elif logs.showing_detail():
            logs.close_detail()
        else:
            event.current_buffer.reset()

    @bindings.add("c-d", filter=idle)
    def _(event: KeyPressEvent) -> None:
        if not event.current_buffer.text:
            event.app.exit()

    @bindings.add("c-q")
    def _(event: KeyPressEvent) -> None:
        event.app.exit()

    return merge_key_bindings([load_key_bindings(), bindings])


__all__ = ["build_key_bindings"]
