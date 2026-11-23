"""Start of the filing run at an event (§F/integrations/paperless/002523).

The finalization of a protocol, a committed transition of an Antrag and a plan version
that comes into force call `request_filing`. It puts one `process_paperless_filings` job
into the arq queue, so the file reaches Paperless at once and not at the next minute
scan. The call never fails: without a pool it does nothing, and an error of the queue
only logs, because the action of the person must not depend on Paperless. The minute scan
of the worker stays, so a lost job is caught up.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("app.paperless")

FILING_TASK_NAME = "process_paperless_filings"


async def request_filing(pool: object | None) -> None:
    """Enqueue one filing run; do nothing without a pool, and only log an error."""
    if pool is None:
        return
    try:
        await pool.enqueue_job(FILING_TASK_NAME)  # type: ignore[attr-defined]
    except Exception:
        logger.exception("paperless filing run was not enqueued")
