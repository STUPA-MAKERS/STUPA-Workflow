"""Pydantic schemas of the media API."""

from __future__ import annotations

from uuid import UUID

from app.shared.schemas import FrozenModel


class MarkdownImageOut(FrozenModel, frozen=True):
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


class MarkdownDocumentOut(FrozenModel, frozen=True):
    """201 response of ``POST /media/documents`` and answer of its info route.

    ``url`` is the canonical Markdown path of the PDF, ``/api/media/documents/<id>``.
    The editor puts it into the text as ``[<name>](<url>)``. ``pages`` is the page
    count of the file badge.
    """

    id: UUID
    url: str
    name: str
    size: int
    pages: int
