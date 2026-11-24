"""Public facade of the protocol service.

`ProtocolService` combines the ops classes. The router, the worker and every other
caller bind to exactly this class:

* `reads.ReadOps`: the access checks of the routes and the reads of a protocol and its PDFs
* `drafts.DraftOps`: create, edit, delete, embed votes, approval, withheld, reopen
* `document.DocumentOps`: the assembly of the render document
* `render.RenderOps`: the render of the internal and the public PDF and their storage
* `finalize.FinalizeOps`: start, render, store and mail the final protocol
* `backfill.BackfillOps`: the backfill of missing public PDFs
"""

from __future__ import annotations

from app.modules.protocol.service.backfill import BackfillOps
from app.modules.protocol.service.drafts import DraftOps
from app.modules.protocol.service.finalize import FinalizeOps
from app.modules.protocol.service.reads import ReadOps


class ProtocolService(ReadOps, DraftOps, FinalizeOps, BackfillOps):
    """Run the protocol operations and the finalization over the shared render stack."""
