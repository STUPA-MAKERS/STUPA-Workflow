"""Shared constants, storage keys, result types and small helpers of the protocol service."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.modules.meetings.protocol_models import Protocol
from app.modules.protocol.markdown import KeeperLine
from app.modules.protocol.public import PublicTop

logger = logging.getLogger("app.protocol")


#: Permanent failures of the public build after which the hourly heal job skips a
#: protocol. A switch of the gremium flag tries it again.
PUBLIC_RENDER_MAX_FAILURES = 3


def protocol_storage_key(protocol_id: UUID) -> str:
    """Build the deterministic MinIO key under the own `pdf/protocol/` prefix."""
    return f"pdf/protocol/{protocol_id}.pdf"


def protocol_public_storage_key(protocol_id: UUID) -> str:
    """Build the MinIO key of the redacted public protocol variant."""
    return f"pdf/protocol/{protocol_id}-public.pdf"


#: Placeholder for the body of a non-public agenda item in the public PDF. The
#: numbering stays and the content is redacted.
_NON_PUBLIC_PLACEHOLDER = "*(nicht-öffentlicher Tagesordnungspunkt)*"


#: Neutral heading for a non-public item in the public PDF. The original title can
#: encode the sensitive subject and must not reach the mailed variant.
_NON_PUBLIC_HEADING = "Nicht-öffentlicher Tagesordnungspunkt"


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """The counts of one public backfill run."""

    done: int = 0
    transient: int = 0
    failed: int = 0


#: The outcome of the public backfill of one protocol.
BackfillOutcome = Literal["done", "transient", "failed"]


@dataclass(frozen=True, slots=True)
class HeaderMeta:
    """The person-related header data of one protocol variant.

    `present_count` holds the one present count of the meeting
    (§F/meetings/meetings/000946) and feeds the quorum, also in the public variant
    that leaves the names out.
    """

    protokollant: str | None = None
    keepers: Sequence[KeeperLine] = field(default_factory=list)
    present: Sequence[str] = field(default_factory=list)
    excused: Sequence[str] = field(default_factory=list)
    absent: Sequence[str] = field(default_factory=list)
    present_count: int = 0
    excused_count: int = 0
    absent_count: int = 0
    guest_count: int = 0
    datalines: Sequence[str] = field(default_factory=list)


def _mark_final(protocol: Protocol, now: datetime) -> None:
    """Set a protocol to final at `now`. The finalization sends no mail (spec 003019).

    `sent_at` keeps the time of an earlier send, because that mail is out and a draft
    that went out must stay (spec 000983). The protocol counts as sent only when
    `sent_at` is at or after `finalized_at` (`is_sent`).
    """
    protocol.status = "final"
    protocol.finalized_at = now


def _mark_sent(protocol: Protocol, now: datetime) -> None:
    """Mark the final protocol as sent at `now`, after its mail went to the queue (003019)."""
    protocol.sent_at = now


def is_sent(protocol: Protocol) -> bool:
    """Return True when the final protocol went out after its last finalization (003019)."""
    sent, final = protocol.sent_at, protocol.finalized_at
    return protocol.status == "final" and sent is not None and (final is None or sent >= final)


def _upload(key: str, pdf: bytes | None) -> tuple[tuple[str, bytes], ...]:
    """Return the upload of a rendered PDF, or none when storage is off."""
    return ((key, pdf),) if pdf is not None else ()


def _redacted_item(number: int) -> tuple[str, PublicTop]:
    """Return the block and the TOP of a non-public item in the public variant."""
    block = "\n\n".join([f"# {_NON_PUBLIC_HEADING}", _NON_PUBLIC_PLACEHOLDER])
    return block, PublicTop(number=number, title=None, nonPublic=True)
