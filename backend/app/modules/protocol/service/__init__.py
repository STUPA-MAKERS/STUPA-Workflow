"""Protocol service.

The service binds to an `AsyncSession` and drives the protocol lifecycle.

* `get_or_create` creates or loads the protocol of a meeting. It is idempotent
  through the UNIQUE `meeting_id`. It takes `gremium_id` and `cd_variant` from
  the meeting and the Gremium.
* `update_markdown` updates the editor body. It accepts a draft only.
* `embed_votes` appends votes as Markdown snippets and writes
  `protocol_vote_ref`. It is idempotent and skips an already referenced vote. A
  vote of another meeting gives 422 `vote_not_in_meeting`.
* `start_finalize` starts the finalization once, and only after the close of the
  meeting. It writes `protocol_finalize`.
* `finalize` renders the Markdown through typst into a PDF. It stores the PDF
  in MinIO and mails it to MAIL_LIST(gremium). It sets `status='final'` and
  `finalized_at`, and `sent_at` when the mail goes out.

The service reuses the typst client, the object storage and the mail queue of
`app.modules.pdf` and `app.modules.notifications` without a change.

Failure discipline: if storage is off by design (dev or demo without MinIO),
`finalize` still completes. The protocol becomes `final` and the mail goes out
without a PDF link. If an EXISTING render or storage backend fails for a short
time, the service raises `ServiceUnavailableError` (503). The session dependency
then rolls back, the protocol stays draft and the caller can repeat the call.

Layout of the package:

``common``
    Constants, storage keys, result types and small helpers.
``snippets``
    The Markdown snippets of votes, elections and polls.
``base``
    Constructor, lookups, output and audit that every ops class shares.
``reads``, ``drafts``, ``document``, ``render``, ``finalize``, ``backfill``
    The ops classes, one concern each.
``service``
    The `ProtocolService` facade that combines them.

This package re-exports the public names, so ``from app.modules.protocol.service import
ProtocolService`` keeps working.
"""

from app.modules.protocol.service.common import (
    PUBLIC_RENDER_MAX_FAILURES,
    BackfillOutcome,
    BackfillResult,
    HeaderMeta,
    protocol_public_storage_key,
    protocol_storage_key,
)
from app.modules.protocol.service.service import ProtocolService
from app.modules.protocol.service.snippets import (
    election_snippet_of,
    poll_meta,
    poll_option_label,
    poll_snippet_of,
    repeat_mark,
)

__all__ = [
    "PUBLIC_RENDER_MAX_FAILURES",
    "BackfillOutcome",
    "BackfillResult",
    "HeaderMeta",
    "ProtocolService",
    "election_snippet_of",
    "poll_meta",
    "poll_option_label",
    "poll_snippet_of",
    "protocol_public_storage_key",
    "protocol_storage_key",
    "repeat_mark",
]
