"""Row doubles for the merge-aware name lookup (`app.modules.auth.identity`).

The lookup selects ``(sub, id, display_name, email, merged id, merged display_name,
merged email)``. A unit test with a fake session queues such rows. The helpers build
them for a plain principal and for a principal that was merged into another one.
"""

from __future__ import annotations

import uuid

RefRow = tuple[
    str, uuid.UUID, str | None, str | None, uuid.UUID | None, str | None, str | None
]


def sub_ref(
    sub: str,
    display_name: str | None,
    email: str | None,
    pid: uuid.UUID | None = None,
    *,
    merged: tuple[uuid.UUID, str | None, str | None] | None = None,
) -> RefRow:
    """A row of a lookup by ``sub``."""
    tid, tdn, tem = merged if merged is not None else (None, None, None)
    return (sub, pid or uuid.uuid4(), display_name, email, tid, tdn, tem)


def id_ref(
    pid: uuid.UUID,
    display_name: str | None,
    email: str | None,
    *,
    merged: tuple[uuid.UUID, str | None, str | None] | None = None,
) -> RefRow:
    """A row of a lookup by principal id."""
    return sub_ref(f"sub-{pid}", display_name, email, pid, merged=merged)
