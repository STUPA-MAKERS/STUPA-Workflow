"""Read and change the UI text overrides and the extra UI languages.

The frontend owns the built-in texts. This service stores only what an admin changes:

- An override replaces the built-in text of one key in one locale. A missing row and a
  NULL value both mean the built-in text. A save with null or a blank text deletes
  the row, so the table holds real overrides only.
- An extra language (`fr`, `pt-BR`, …) has no built-in texts. Each of its keys falls
  back along the chain `<code>` → `en` → `de`, because a reader of a third language
  more often reads English than German. EN falls back to DE.

Every change writes a `config_change` audit entry without a revision, so the audit
log cannot revert it. The entry names the keys and counts, never the texts.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.translations.catalog import (
    BuiltinText,
    builtin_texts,
    catalog,
    placeholders_of,
)
from app.modules.translations.models import UiLanguage, UiTranslation
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

#: The locales whose texts the frontend ships. They have no `ui_language` row.
BUILTIN_LOCALES: tuple[str, ...] = ("de", "en")
DEFAULT_LOCALE = "de"

AUDIT_TEXTS = "ui_translation"
AUDIT_LANGUAGE = "ui_language"

#: The most keys that the audit entry of one save names. The counts stay exact.
_AUDIT_KEYS = 200


def fallback_chain(locale: str) -> list[str]:
    """Return the locales whose texts `locale` shows, the first one first.

    DE is the reference and has no fallback. EN falls back to DE. An extra language
    falls back to EN and then to DE.
    """
    if locale == DEFAULT_LOCALE:
        return [DEFAULT_LOCALE]
    if locale == "en":
        return ["en", DEFAULT_LOCALE]
    return [locale, "en", DEFAULT_LOCALE]


class TranslationService:
    """The overrides and the extra languages."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a session."""
        self.session = session

    async def languages(self, *, active_only: bool) -> list[UiLanguage]:
        """Return the extra languages by code, or only the active ones."""
        stmt = select(UiLanguage).order_by(UiLanguage.code)
        if active_only:
            stmt = stmt.where(UiLanguage.active.is_(True))
        return list((await self.session.scalars(stmt)).all())

    async def create_language(
        self, *, code: str, name: str, active: bool, actor: str
    ) -> UiLanguage:
        """Add an extra language and commit.

        Raises:
            ConflictError: The code is built-in (`language_builtin`) or exists
                (`language_exists`).
        """
        if code in BUILTIN_LOCALES:
            raise ConflictError("de and en are built in", code="language_builtin")
        if await self.session.get(UiLanguage, code) is not None:
            raise ConflictError("the language exists", code="language_exists")
        now = datetime.now(UTC)
        row = UiLanguage(
            code=code, name=name, active=active, created_at=now, updated_at=now, updated_by=actor
        )
        self.session.add(row)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_CHANGE,
            target_type=AUDIT_LANGUAGE,
            target_id=code,
            data={"created": True, "name": name, "active": active},
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def update_language(
        self, code: str, *, name: str | None, active: bool | None, actor: str
    ) -> UiLanguage:
        """Change the name or the switch of an extra language and commit.

        Raises:
            NotFoundError: No extra language has this code.
        """
        row = await self._language(code)
        data: dict[str, object] = {}
        if name is not None and name != row.name:
            data["name"] = {"from": row.name, "to": name}
            row.name = name
        if active is not None and active != row.active:
            data["active"] = {"from": row.active, "to": active}
            row.active = active
        if data:
            row.updated_at = datetime.now(UTC)
            row.updated_by = actor
            await audit_record(
                self.session,
                actor=actor,
                action=AuditAction.CONFIG_CHANGE,
                target_type=AUDIT_LANGUAGE,
                target_id=code,
                data=data,
            )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def delete_language(self, code: str, *, actor: str) -> None:
        """Delete an extra language with all its overrides and commit.

        Raises:
            NotFoundError: No extra language has this code.
        """
        row = await self._language(code)
        removed = await self.session.scalars(
            delete(UiTranslation).where(UiTranslation.locale == code).returning(UiTranslation.key)
        )
        count = len(removed.all())
        await self.session.delete(row)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_CHANGE,
            target_type=AUDIT_LANGUAGE,
            target_id=code,
            data={"deleted": True, "overrides": count},
        )
        await self.session.commit()

    async def overrides(self, locale: str) -> dict[str, str]:
        """Return the overrides of `locale`, key to text. NULL rows are left out."""
        rows = await self.session.execute(
            select(UiTranslation.key, UiTranslation.value).where(
                UiTranslation.locale == locale, UiTranslation.value.is_not(None)
            )
        )
        return {key: value for key, value in rows if value is not None}

    async def admin_overrides(self, locale: str) -> dict[str, str]:
        """Return the overrides of a known locale, inactive extra languages included.

        Raises:
            NotFoundError: The locale is neither built-in nor an extra language.
        """
        await self._check_locale(locale)
        return await self.overrides(locale)

    async def builtin(
        self, *, prefix: str | None, locale: str | None, untranslated: bool
    ) -> list[tuple[str, BuiltinText, str | None]]:
        """Return the built-in texts by key, each with the override of `locale`.

        `prefix` keeps the keys that start with it. `untranslated` keeps the keys
        without an override in `locale`, so a translator finds the open work.

        Raises:
            NotFoundError: The locale is neither built-in nor an extra language.
            ValidationProblem: `untranslated` without a locale (`locale_required`).
        """
        if untranslated and locale is None:
            raise ValidationProblem(
                "untranslated needs a locale",
                code="locale_required",
                errors=[{"field": "locale", "msg": "required"}],
            )
        own: dict[str, str] = {}
        if locale is not None:
            own = await self.admin_overrides(locale)
        rows: list[tuple[str, BuiltinText, str | None]] = []
        for key, text in builtin_texts().items():
            if prefix is not None and not key.startswith(prefix):
                continue
            if untranslated and key in own:
                continue
            rows.append((key, text, own.get(key)))
        return rows

    async def save(
        self, locale: str, changes: dict[str, str | None], *, actor: str
    ) -> dict[str, str]:
        """Apply the changes of one save and commit. Return the overrides after it.

        A text sets the override, null or a blank text deletes it. The method checks
        every key before it writes, so one refusal changes nothing.

        Raises:
            NotFoundError: The locale is neither built-in nor an extra language.
            ValidationProblem: A key is not in the catalog (`unknown_key`), or a text
                lacks a placeholder of the built-in text or adds one
                (`placeholder_mismatch`). `errors` names each key.
        """
        await self._check_locale(locale)
        known = catalog()
        unknown = sorted(key for key in changes if key not in known)
        if unknown:
            raise ValidationProblem(
                "unknown text keys",
                code="unknown_key",
                errors=[{"field": key, "msg": "unknown key"} for key in unknown[:50]],
            )
        clean = {key: (v if v is not None and v.strip() else None) for key, v in changes.items()}
        wrong = sorted(
            key
            for key, value in clean.items()
            if value is not None and placeholders_of(value) != known[key]
        )
        if wrong:
            raise ValidationProblem(
                "a text must keep the placeholders of the built-in text",
                code="placeholder_mismatch",
                errors=[
                    {"field": key, "msg": "expected " + " ".join(f"{{{n}}}" for n in known[key])}
                    for key in wrong[:50]
                ],
            )
        cleared = sorted(key for key, value in clean.items() if value is None)
        written = {key: value for key, value in clean.items() if value is not None}
        if cleared:
            await self.session.execute(
                delete(UiTranslation).where(
                    UiTranslation.locale == locale, UiTranslation.key.in_(cleared)
                )
            )
        if written:
            now = datetime.now(UTC)
            stmt = insert(UiTranslation).values(
                [
                    {
                        "locale": locale,
                        "key": key,
                        "value": value,
                        "updated_at": now,
                        "updated_by": actor,
                    }
                    for key, value in written.items()
                ]
            )
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[UiTranslation.locale, UiTranslation.key],
                    set_={
                        "value": stmt.excluded.value,
                        "updated_at": stmt.excluded.updated_at,
                        "updated_by": stmt.excluded.updated_by,
                    },
                )
            )
        if written or cleared:
            keys = sorted(clean)
            await audit_record(
                self.session,
                actor=actor,
                action=AuditAction.CONFIG_CHANGE,
                target_type=AUDIT_TEXTS,
                target_id=locale,
                data={"set": len(written), "cleared": len(cleared), "keys": keys[:_AUDIT_KEYS]},
            )
        await self.session.commit()
        return await self.overrides(locale)

    async def bundle(
        self, requested: str | None
    ) -> tuple[str, list[UiLanguage], dict[str, dict[str, str]]]:
        """Resolve the UI locale and return it with the active languages and the overrides.

        The requested locale applies when it is built-in or an active extra language;
        anything else resolves to DE. The overrides cover the fallback chain of the
        resolved locale.
        """
        active = await self.languages(active_only=True)
        codes = {row.code for row in active}
        locale = DEFAULT_LOCALE
        if requested is not None and (requested in BUILTIN_LOCALES or requested in codes):
            locale = requested
        overrides = {code: await self.overrides(code) for code in fallback_chain(locale)}
        return locale, active, overrides

    async def _language(self, code: str) -> UiLanguage:
        row = await self.session.get(UiLanguage, code)
        if row is None:
            raise NotFoundError("unknown language", code="language_not_found")
        return row

    async def _check_locale(self, locale: str) -> None:
        if locale not in BUILTIN_LOCALES:
            await self._language(locale)
