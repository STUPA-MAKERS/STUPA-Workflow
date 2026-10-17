"""Pydantic schemas of the media API."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class MarkdownImageOut(BaseModel):
    """201 response of ``POST /media/images``.

    ``url`` is the canonical Markdown path of the image, ``/api/media/images/<id>``.
    The editor puts it into the text as ``![alt](<url>)``.
    """

    id: UUID
    url: str
    mime: str
    width: int
    height: int
    size: int
