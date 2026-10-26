"""Tables of the UI text overrides and of the extra UI languages.

`ui_translation` holds one override per locale and key. A missing row and a row with
`value` NULL both mean "the built-in text", so the table only ever overrides the
catalog of the frontend. `ui_language` holds the languages that an admin adds beside
the built-in `de` and `en`. The built-in ones have no row.
"""

from __future__ import annotations

from datetime import datetime as _datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UiLanguage(Base):
    """An extra UI language: a BCP 47 code, its native name and the switch `active`.

    An inactive language shows only on the admin page. The language switch of the app
    lists the active ones after DE and EN.
    """

    __tablename__ = "ui_language"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[_datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[_datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("code NOT IN ('de', 'en')", name="not_builtin"),
        CheckConstraint("length(code) BETWEEN 2 AND 16", name="code_length"),
        CheckConstraint("length(name) BETWEEN 1 AND 64", name="name_length"),
    )


class UiTranslation(Base):
    """The override of one UI text in one locale. `value` NULL means the built-in text."""

    __tablename__ = "ui_translation"

    locale: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[_datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
