"""Config tables of the admin module.

The module owns ``site_config_version``, the corporate-design tables ``cd_variant``
with ``cd_variant_logo``, and ``export_logo``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class CdVariant(UUIDPkMixin, CreatedAtMixin, Base):
    """Corporate-design variant — an admin-managed set of document logos.

    A variant controls the title-page logos and the footer logos of a rendered
    document plus its display name. It controls no color and no font. The
    platform can hold arbitrarily many variants.

    ``key`` is the stable slug. It is immutable after the create, because the
    render path and the seed data reference it.

    A variant does not set the document shape. The application render pins the report
    shape and the protocol render pins the protocol shape, because the shape follows the
    kind of document and not the design of the Gremium that owns it.
    """

    __tablename__ = "cd_variant"

    key: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)


class CdVariantLogo(UUIDPkMixin, CreatedAtMixin, Base):
    """One logo of a corporate-design variant, in one slot at one position.

    A row is EITHER a vendored logo (``vendored_name``) OR an uploaded
    object in MinIO (``object_key`` with ``file_name``, ``mime`` and ``size``).
    The check constraint ``ck_cd_variant_logo_source`` holds the exactly-one-of
    rule in the database, so no code path can write a row with both or neither.

    ``position`` orders the logos inside one slot, lowest first.

    The slot ``square`` holds the 1:1 logo that the app shows for a Gremium. The
    partial unique index ``uq_cd_variant_logo_square`` allows at most one such
    row per variant. The render path ignores the slot.
    """

    __tablename__ = "cd_variant_logo"

    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cd_variant.id", ondelete="CASCADE"))
    slot: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    vendored_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint("slot IN ('title','footer','square')", name="slot"),
        CheckConstraint("(vendored_name IS NULL) <> (object_key IS NULL)", name="source"),
        Index(
            "ix_cd_variant_logo_variant_id_slot_position",
            "variant_id",
            "slot",
            "position",
        ),
        Index(
            "uq_cd_variant_logo_square",
            "variant_id",
            unique=True,
            postgresql_where=text("slot = 'square'"),
        ),
    )


class SiteConfigVersion(UUIDPkMixin, CreatedAtMixin, Base):
    """Versioned branding and site config.

    The table is versioned like form and flow. A save writes a new version and
    never edits a row in place. At most one row is ``active``, held by the
    partial unique index ``WHERE active``. ``branding`` holds the
    schema-validated JSON. ``created_by`` holds the OIDC ``sub`` of the
    activating principal, so it carries no PII.
    """

    __tablename__ = "site_config_version"

    version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    branding: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("version", name="uq_site_config_version_version"),
        Index(
            "uq_site_config_version_one_active",
            "active",
            unique=True,
            postgresql_where=text("active"),
        ),
    )


class ExportLogo(UUIDPkMixin, CreatedAtMixin, Base):
    """The export logo of the branding: the one logo of every exported PDF (spec 000891).

    The table holds at most one row: ``singleton`` is always true and unique. The bytes
    live in the object storage under ``object_key``; they reach the render service only,
    never the browser, so SVG and PDF are allowed. ``mime`` is the sniffed type.
    ``created_by`` holds the OIDC ``sub`` of the uploader, so it carries no PII.
    """

    __tablename__ = "export_logo"

    singleton: Mapped[bool] = mapped_column(Boolean, server_default="true")
    object_key: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("singleton", name="uq_export_logo_singleton"),
        CheckConstraint("singleton", name="singleton"),
    )
