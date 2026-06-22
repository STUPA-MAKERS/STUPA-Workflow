"""AUD-048: the dedup pre-check query must be scoped to the concrete candidate
idempotency keys (``IN``), not load every key ever issued for the event.

``FakeSession`` ignores the statement, so we use a capturing session that records
the compiled bound parameters of the ``_existing_keys`` query and assert they equal
exactly the keys derived from the fetched webhooks.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.admin.models import Webhook
from app.modules.webhooks.service import WebhookService
from app.settings import load_settings
from tests._support.webhooks_fakes import FakeResult, FakeSession, FakeWebhookQueue

SETTINGS = load_settings()


def _hook() -> Webhook:
    hook = Webhook(
        name="h", url="https://hook.test/h", events=["status_changed"],
        active=True, secret=b"k",
    )
    hook.id = uuid.uuid4()
    return hook


class _CapturingSession(FakeSession):
    """Records the bound parameters of every ``scalars`` query."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.in_params: list[list[str]] = []

    async def scalars(self, stmt: Any) -> FakeResult:
        compiled = stmt.compile()
        # Only record the dedup pre-check query (the one with the IN clause on
        # idempotency_key); ignore the unrelated webhook-lookup query.
        if "idempotency_key IN" in str(compiled):
            keys = [
                v for k, v in compiled.params.items()
                if k.startswith("idempotency_key")
            ]
            flat: list[str] = []
            for v in keys:  # in_ expands to one tuple-valued POSTCOMPILE param
                flat.extend(v if isinstance(v, (list, tuple)) else [v])
            self.in_params.append(flat)
        return await super().scalars(stmt)


async def test_dispatch_event_scopes_dedup_query_to_candidate_keys() -> None:
    h1, h2 = _hook(), _hook()
    base = "app:evt:0:webhook"
    session = _CapturingSession(scalars=[[h1, h2], []])
    n = await WebhookService(session, SETTINGS, queue=FakeWebhookQueue()).dispatch_event(  # type: ignore[arg-type]
        "status_changed", idempotency_base=base
    )
    assert n == 2
    # The dedup query bound EXACTLY the two candidate keys (one per fetched webhook),
    # not an unbounded scan of all historical keys for the event.
    assert session.in_params == [[f"{base}:{h1.id}", f"{base}:{h2.id}"]]


async def test_dispatch_to_webhook_scopes_dedup_query_to_single_key() -> None:
    hook = _hook()
    base = "app:evt:0:webhook"
    session = _CapturingSession(scalars=[[]])
    session.store[hook.id] = hook
    n = await WebhookService(session, SETTINGS, queue=FakeWebhookQueue()).dispatch_to_webhook(  # type: ignore[arg-type]
        hook.id, event="status_changed", idempotency_base=base
    )
    assert n == 1
    assert session.in_params == [[f"{base}:{hook.id}"]]
