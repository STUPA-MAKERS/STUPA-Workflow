"""API-Schemata des application-types-Moduls (T-25).

Listen-DTO der Antragstypen. Casing folgt dem übrigen Backend (camelCase-Aliase,
`populate_by_name`, vgl. applications/forms §5). ``name`` ist die für ``lang``
aufgelöste i18n-Bezeichnung (overview §5) — das FE konsumiert einen fertigen String,
nicht die rohe ``*_i18n``-Map.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.paging import PageParams


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class ApplicationTypeListQuery(PageParams):
    """Query-Parameter der Typen-Liste: Paging (``limit``/``offset``) + ``lang``.

    ``extra="forbid"`` → unbekannte Query-Parameter werden mit 422 abgelehnt (statt
    still ignoriert); hält den Contract negativ-konform (schemathesis
    ``negative_data_rejection``).

    ``offset`` ist zusätzlich nach oben begrenzt: ein absurd großer Wert (> int4)
    ließe das DB-``OFFSET`` overflowen → 500. Mit ``le`` wird er sauber als 422
    abgelehnt (schemathesis ``server_error``).
    """

    model_config = ConfigDict(extra="forbid")

    # int4-Max: rein zur Overflow-Abwehr, keine fachliche Seiten-Obergrenze.
    offset: int = Field(default=0, ge=0, le=2_147_483_647)
    lang: str = "de"


class ApplicationTypeListItem(_CamelModel):
    """Ein Antragstyp in der Liste.

    Öffentliche Felder sind für die Antragstellung relevant (``id``/``name``/
    ``hasBudget``/``active``/``activeFormVersionId``). ``key`` und ``gremiumId``
    sind Admin-Zusatzfelder und nur bei berechtigtem Principal gefüllt (sonst
    ``null``).
    """

    id: UUID
    name: str
    has_budget: bool = Field(alias="hasBudget")
    # `active` = für die Antragstellung anbietbar (es gibt eine aktive Form-Version).
    active: bool
    active_form_version_id: UUID | None = Field(default=None, alias="activeFormVersionId")
    # Admin-Zusatzfelder (nur bei Berechtigung gefüllt).
    key: str | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
