"""The access log filter masks the token of a push action and a calendar feed."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from app.logging_config import TOKEN_MASK, TokenPathFilter, mask_token_path


@pytest.mark.parametrize(
    ("path", "masked"),
    [
        ("/api/push/actions/abc.DEF-1", f"/api/push/actions/{TOKEN_MASK}"),
        ("/api/push/actions/abc?x=1", f"/api/push/actions/{TOKEN_MASK}?x=1"),
        ("/api/calendar/tok123.ics", f"/api/calendar/{TOKEN_MASK}.ics"),
        ("/api/calendar/tok123.ics?v=2", f"/api/calendar/{TOKEN_MASK}.ics?v=2"),
        ("/api/calendar/entries", "/api/calendar/entries"),
        ("/api/public/calendar.ics", "/api/public/calendar.ics"),
        ("/api/applications/1", "/api/applications/1"),
    ],
)
def test_mask_token_path(path: str, masked: str) -> None:
    assert mask_token_path(path) == masked


def test_filter_masks_the_path_of_an_access_record() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/api/push/actions/secret", "1.1", 204),
        None,
    )
    assert TokenPathFilter().filter(record) is True
    line = record.getMessage()
    assert "secret" not in line
    assert f"/api/push/actions/{TOKEN_MASK}" in line


def test_filter_keeps_a_record_without_access_args() -> None:
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "plain", None, None)
    assert TokenPathFilter().filter(record) is True
    assert record.getMessage() == "plain"


#: The nginx configuration of the web image; from tests/unit/, parents[3] is the repo root.
NGINX_CONF = Path(__file__).resolve().parents[3] / "deploy" / "web" / "nginx.conf"


def _nginx_masks() -> list[tuple[re.Pattern[str], str]]:
    """Read the regex lines of the map `$ap_log_request` as Python patterns."""
    text = NGINX_CONF.read_text(encoding="utf-8")
    block = text[text.index("map $request $ap_log_request") :]
    block = block[: block.index("\n}")]
    lines = re.findall(r'"~(.+?)"\s+"(.+?)";', block)
    return [
        (re.compile(pattern.replace("(?<", "(?P<")), re.sub(r"\$\{(\w+)\}", r"\\g<\1>", value))
        for pattern, value in lines
    ]


def _nginx_line(request: str) -> str:
    return next(
        (
            pattern.sub(value, request)
            for pattern, value in _nginx_masks()
            if pattern.match(request)
        ),
        request,
    )


@pytest.mark.parametrize(
    ("request_line", "logged"),
    [
        ("GET /api/push/actions/SECRET HTTP/1.1", "GET /api/push/actions/*** HTTP/1.1"),
        ("GET /api/push/actions/SECRET?x=1 HTTP/1.1", "GET /api/push/actions/***?x=1 HTTP/1.1"),
        ("GET /api/calendar/SECRET.ics HTTP/1.1", "GET /api/calendar/***.ics HTTP/1.1"),
        ("GET /api/calendar/entries HTTP/1.1", "GET /api/calendar/entries HTTP/1.1"),
        ("GET /api/applications HTTP/1.1", "GET /api/applications HTTP/1.1"),
    ],
)
def test_nginx_access_log_masks_the_token(request_line: str, logged: str) -> None:
    assert _nginx_line(request_line) == logged


def test_nginx_server_logs_with_the_masked_format() -> None:
    text = NGINX_CONF.read_text(encoding="utf-8")
    assert "log_format ap_masked" in text
    assert '"$ap_log_request"' in text
    assert "access_log /var/log/nginx/access.log ap_masked;" in text
