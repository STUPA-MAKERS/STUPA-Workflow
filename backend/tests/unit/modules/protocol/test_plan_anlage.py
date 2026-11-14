"""The render of the plan that a protocol appends reports a failed render."""

from __future__ import annotations

from typing import Any, cast

import pytest

from app.modules.budget.plan_export import PlanFile
from app.modules.pdf.typst_client import TypstError
from app.modules.protocol import plan_anlage
from app.shared.errors import BadRequestError, ServiceUnavailableError

_FILE = PlanFile(source="plan", config={}, name="plan.pdf")


class _Typst:
    """A render service that fails."""

    def __init__(self, *, retryable: bool) -> None:
        self._retryable = retryable

    async def render_pdf(self, *_args: object, **_kwargs: object) -> bytes:
        """Fail as the render service does."""
        raise TypstError("no", retryable=self._retryable)


async def _render(*, retryable: bool) -> bytes:
    """Render a plan through a failing service."""
    return await plan_anlage._render(
        cast("Any", _Typst(retryable=retryable)), cast("Any", None), _FILE
    )


@pytest.fixture(autouse=True)
def _no_export_logo(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(_session: object) -> None:
        return None

    monkeypatch.setattr(plan_anlage, "active_export_logo", none)


@pytest.mark.asyncio
async def test_a_permanent_render_error_is_a_bad_request() -> None:
    with pytest.raises(BadRequestError) as caught:
        await _render(retryable=False)
    assert caught.value.code == "render_failed"


@pytest.mark.asyncio
async def test_a_transient_render_error_is_unavailable() -> None:
    with pytest.raises(ServiceUnavailableError):
        await _render(retryable=True)
