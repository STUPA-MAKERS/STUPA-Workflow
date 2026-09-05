"""Schemas for the global search.

A hit is deliberately flat and presentational. The palette that renders it must not
need to know the shape of an application, an invoice or a meeting — it needs a line to
show, a line under it, and somewhere to go.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: The kinds a hit can have. The client groups by this and picks the icon and label,
#: so the value is a stable key and never a translated string.
SearchKind = Literal[
    "application",
    "meeting",
    "invoice",
    "expense",
    "budget",
    "gremium",
    "principal",
]


class SearchHit(BaseModel):
    """One result row."""

    kind: SearchKind
    id: str
    #: The line the reader scans. Never empty: a record without a title falls back to
    #: something identifying, so a hit is never a blank row.
    title: str
    #: Context under the title — a state, a committee, an amount. Optional.
    subtitle: str | None = None
    #: Where the palette navigates. App-relative, and always a route the client has.
    url: str
    #: The record is archived. Applications only; the palette marks such a hit, because
    #: an archived record is otherwise indistinguishable from a current one.
    archived: bool = False


class SearchResults(BaseModel):
    """Everything found for one query, in one round trip."""

    hits: list[SearchHit]
    #: True when at least one source had more matches than the per-kind cap. The client
    #: says so rather than implying that this is everything.
    truncated: bool = False
    #: Sources that failed. The search degrades instead of returning nothing when one
    #: module errors: a palette that shows four kinds beats one that shows a stack trace.
    failed: list[str] = Field(default_factory=list)
