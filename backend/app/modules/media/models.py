"""Markdown images: the ``markdown_image`` table.

One row holds one uploaded image of a Markdown text (protocol, to-do card, chat
message). The bytes live in the attachment bucket under ``media/images/<id>``, never
in the database. The Markdown refers to the image by the canonical path
``/api/media/images/<id>`` only.

The row has no uploader column on purpose. A link to a principal would make the
image part of the account merge and of the erasure, and the image itself holds no
personal metadata: the upload strips it. The id is a random uuid4, so it cannot be
guessed.
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, CheckConstraint, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin

#: The object-key prefix of a Markdown image in the attachment bucket.
IMAGE_KEY_PREFIX = "media/images/"

#: The stored types. They are the input types: the upload keeps the format.
IMAGE_MIMES: tuple[str, ...] = ("image/png", "image/jpeg", "image/gif", "image/webp")


def image_storage_key(image_id: uuid.UUID) -> str:
    """Return the object key of an image."""
    return f"{IMAGE_KEY_PREFIX}{image_id}"


class MarkdownImage(CreatedAtMixin, Base):
    """An uploaded, re-encoded image that a Markdown text refers to."""

    __tablename__ = "markdown_image"
    __table_args__ = (
        CheckConstraint(
            "mime IN ('image/png', 'image/jpeg', 'image/gif', 'image/webp')",
            name="mime",
        ),
        CheckConstraint("size >= 0", name="size"),
        CheckConstraint("width > 0 AND height > 0", name="dimensions"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
