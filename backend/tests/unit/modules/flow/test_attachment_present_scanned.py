"""F13: the guard `attachmentPresent` counts only scanned, clean attachments.

A file that waits for the ClamAV scan is in quarantine. It must not open a transition
that requires an attachment. The test reads the query that `_has_attachment` sends.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.modules.flow.context import _has_attachment


class _CaptureSession:
    def __init__(self) -> None:
        self.statement: Any = None

    async def scalar(self, stmt: Any) -> bool:
        self.statement = stmt
        return True


async def test_query_requires_scanned_clean_and_stored() -> None:
    session = _CaptureSession()
    app = SimpleNamespace(id=uuid4())
    assert await _has_attachment(cast("Any", session), cast("Any", app)) is True
    sql = str(
        session.statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "attachment.scanned IS true" in sql
    assert "attachment.scan_result = 'clean'" in sql
    assert "attachment.storage_key IS NOT NULL" in sql
