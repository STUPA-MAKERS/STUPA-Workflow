"""Visual theme for the admin CLI.

The module holds one prompt_toolkit `Style` plus the row-highlight colors as plain
constants. The log renderer and the floating panels then agree on those colors. The
palette puts the coral accent of the platform on a near-black base. This keeps the
identity of the web frontend in a command REPL.
"""

from prompt_toolkit.styles import Style

CORAL = "#d97757"

# Row-highlight backgrounds. Hover uses a warm neutral. The popped-out detail uses
# a deeper coral-tinted shade, so the panel reads as a part of its row.
HOVER_HIGHLIGHT = "#33302b"
DETAIL_HIGHLIGHT = "#4a2e22"

STYLE = Style.from_dict(
    {
        # input line
        "prompt": f"bold {CORAL}",
        "cont": "#3a3a3a",
        "command": f"bold {CORAL}",
        # completion menu
        "comp": "#9e9e9e",
        "comp-sel": f"bold {CORAL} reverse",
        # inline selector
        "select-title": f"bold {CORAL}",
        "select-pointer": f"bold {CORAL}",
        "select-active": f"bold {CORAL}",
        "select-key": "#6c6c6c",
        "select-hint": "#6c6c6c",
        # log rows
        "time": "#6c6c6c",
        "dim": "#8a8a8a",
        "head": f"bold {CORAL}",
        "sep": "#4a4a4a",
        "info": "#5fafff",
        "error": "bold #ff5f5f",
        "warn": "bold #ff9d5c",
        "value": "#e8e6e3",
        # entity accents
        "active": "#87d7af",
        "inactive": "#6c6c6c",
        "email": "#e8e6e3",
        "id": "#6c6c6c",
        # audit action categories
        "act-auth": "#5fd7ff",
        "act-status": "#5fafff",
        "act-budget": "#87d7af",
        "act-config": "#e5c07b",
        "act-privacy": "#d78787",
        "act-vote": CORAL,
        "act-delete": "bold #ff5f5f",
        "act-plain": "#c0c0c0",
        # floating panels
        "detail-accent": f"bold {CORAL}",
        "frame.border": "#5f5f5f",
        "frame.label": f"bold {CORAL}",
        # bottom toolbar
        "bottom-toolbar": "noreverse bold #9e9e9e",
        "on": "noreverse bold #87d7af",
        "off": "noreverse bold #ff8787",
        "ro": "noreverse bold #ff9d5c",
        "scroll-btn": f"bold #1c1c1c bg:{CORAL}",
    }
)

__all__ = ["STYLE", "CORAL", "HOVER_HIGHLIGHT", "DETAIL_HIGHLIGHT"]
