"""UI text overrides and extra UI languages.

Public (no login, because the login page and the public pages are translated too):

- ``GET /i18n?locale=`` — the resolved UI locale, the active extra languages and the
  overrides of the fallback chain. ``Cache-Control: no-cache``, so a save shows at the
  next start of the app.

Admin (``admin.translations``):

- ``GET|POST /admin/translations/languages``, ``PATCH|DELETE .../languages/{code}`` —
  the extra languages. A delete removes the overrides of the language too.
- ``GET /admin/translations/builtin?prefix=&locale=&untranslated=`` — the built-in DE
  and EN texts by key, each with the override of ``locale``. ``untranslated`` keeps
  the keys without an override in ``locale``.
- ``GET|PUT /admin/translations/texts/{locale}`` — the overrides of one locale, inactive
  extra languages included. The PUT applies a set of changes (text, or null for the
  built-in text).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.deps import DbSession, Principal, require_principal
from app.modules.translations.schemas import (
    LANGUAGE_CODE_PATTERN,
    BuiltinTextOut,
    BuiltinTextsOut,
    I18nBundleOut,
    LanguageCreate,
    LanguageOut,
    LanguageUpdate,
    PublicLanguageOut,
    TextsOut,
    TextsUpdate,
)
from app.modules.translations.service import TranslationService
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/admin/translations", tags=["translations"])
public_router = APIRouter(tags=["translations"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_translation_service(session: DbSession) -> TranslationService:
    """Build the translation service."""
    return TranslationService(session)


ServiceDep = Annotated[TranslationService, Depends(get_translation_service)]
TranslationsAdmin = Annotated[Principal, Depends(require_principal("admin.translations"))]
LocalePath = Annotated[str, Path(pattern=LANGUAGE_CODE_PATTERN, max_length=16)]


@public_router.get("/i18n", response_model=I18nBundleOut, responses=_errors(422))
async def get_i18n_bundle(
    service: ServiceDep,
    response: Response,
    locale: Annotated[str | None, Query(max_length=16)] = None,
) -> I18nBundleOut:
    """Return the UI locale for ``locale``, the active extra languages and the overrides.

    An unknown or inactive ``locale`` resolves to ``de``.
    """
    resolved, languages, overrides = await service.bundle(locale)
    response.headers["Cache-Control"] = "no-cache"
    return I18nBundleOut(
        locale=resolved,
        languages=[PublicLanguageOut(code=row.code, name=row.name) for row in languages],
        overrides=overrides,
    )


@router.get(
    "/languages",
    response_model=list[LanguageOut],
    dependencies=[Depends(require_principal("admin.translations"))],
    responses=_errors(401, 403),
)
async def list_languages(service: ServiceDep) -> list[LanguageOut]:
    """Return every extra language, inactive ones included."""
    rows = await service.languages(active_only=False)
    return [LanguageOut.model_validate(row, from_attributes=True) for row in rows]


@router.post(
    "/languages",
    response_model=LanguageOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(400, 401, 403, 409, 422),
)
async def create_language(
    payload: LanguageCreate, service: ServiceDep, principal: TranslationsAdmin
) -> LanguageOut:
    """Add an extra language. ``de`` and ``en`` are built in (409)."""
    row = await service.create_language(
        code=payload.code, name=payload.name, active=payload.active, actor=principal.sub
    )
    return LanguageOut.model_validate(row, from_attributes=True)


@router.patch(
    "/languages/{code}",
    response_model=LanguageOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_language(
    code: LocalePath, payload: LanguageUpdate, service: ServiceDep, principal: TranslationsAdmin
) -> LanguageOut:
    """Rename an extra language or switch it on or off."""
    row = await service.update_language(
        code, name=payload.name, active=payload.active, actor=principal.sub
    )
    return LanguageOut.model_validate(row, from_attributes=True)


@router.delete(
    "/languages/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404, 422),
)
async def delete_language(
    code: LocalePath, service: ServiceDep, principal: TranslationsAdmin
) -> Response:
    """Delete an extra language and all its overrides."""
    await service.delete_language(code, actor=principal.sub)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/builtin",
    response_model=BuiltinTextsOut,
    dependencies=[Depends(require_principal("admin.translations"))],
    responses=_errors(401, 403, 404, 422),
)
async def get_builtin_texts(
    service: ServiceDep,
    prefix: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    locale: Annotated[str | None, Query(pattern=LANGUAGE_CODE_PATTERN, max_length=16)] = None,
    untranslated: bool = False,
) -> BuiltinTextsOut:
    """Return the built-in texts, each with the override of ``locale``.

    ``untranslated`` needs ``locale`` (422 ``locale_required``) and keeps the keys
    without an override in it.
    """
    rows = await service.builtin(prefix=prefix, locale=locale, untranslated=untranslated)
    return BuiltinTextsOut(
        locale=locale,
        texts=[BuiltinTextOut(key=key, de=text.de, en=text.en, own=own) for key, text, own in rows],
    )


@router.get(
    "/texts/{locale}",
    response_model=TextsOut,
    dependencies=[Depends(require_principal("admin.translations"))],
    responses=_errors(401, 403, 404, 422),
)
async def get_texts(locale: LocalePath, service: ServiceDep) -> TextsOut:
    """Return the overrides of one locale."""
    return TextsOut(locale=locale, overrides=await service.admin_overrides(locale))


@router.put(
    "/texts/{locale}",
    response_model=TextsOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def put_texts(
    locale: LocalePath, payload: TextsUpdate, service: ServiceDep, principal: TranslationsAdmin
) -> TextsOut:
    """Apply a set of changes: a text sets the override, null restores the built-in text.

    A key outside the catalog (``unknown_key``) or a text whose placeholders differ from
    the built-in text (``placeholder_mismatch``) refuses the whole save (422).
    """
    overrides = await service.save(locale, payload.changes, actor=principal.sub)
    return TextsOut(locale=locale, overrides=overrides)
