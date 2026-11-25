"""The checks of an Antrag across fields: form rules and the root of a cost-center field.

`validate_answers` checks one field at a time and has no database. These checks need the
effective form with its rules and with the options that the server injects, so the
create and the edit of an Antrag run them after `validate_answers`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.budget.form_options import internal_ids
from app.modules.forms.schemas import EffectiveFormOut
from app.modules.forms.validation import broken_rules, outside_subtree
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ValidationProblem

#: The code of a 422 for an answer that breaks a rule with ``block`` (spec 001671).
FORM_RULE_FAILED = "form_rule_failed"
#: The code of a 422 for a cost center outside the root of its field (spec 001681).
COST_CENTRE_OUTSIDE_SUBTREE = "cost_centre_outside_subtree"
#: The code of a 422 for an Intern cost center in a form field (spec 003012).
COST_CENTRE_INTERNAL = "cost_centre_internal"


def check_form_rules(
    effective: EffectiveFormOut,
    data: Mapping[str, Any],
    *,
    changed: frozenset[str] | None = None,
) -> None:
    """Refuse answers that break a ``block`` rule or leave the root of a cost-center field.

    A rule with ``warn`` never refuses. ``changed`` names the keys that an edit changed;
    the root check then reads only these fields, because a cost center of an older answer
    can leave the root when the tree moves, and that must not block an edit of another
    field. ``None`` (the create) checks every field.

    Raises:
        ValidationProblem: 422 ``cost_centre_outside_subtree`` with the field, or 422
            ``form_rule_failed`` with one error per broken rule, its index and its message.
    """
    fields: Sequence[FormFieldDef] = [f for s in effective.sections for f in s.fields]
    checked = [f for f in fields if changed is None or f.key in changed]
    outside = outside_subtree(checked, data)
    if outside:
        raise ValidationProblem(
            "The cost centre is outside the root of its field.",
            code=COST_CENTRE_OUTSIDE_SUBTREE,
            errors=[{"field": e.field, "msg": e.msg} for e in outside],
        )
    blocking = [
        (i, rule)
        for i, rule in broken_rules(effective.rules, fields, data)
        if rule.severity == "block"
    ]
    if blocking:
        raise ValidationProblem(
            "The answers break a rule of the form.",
            code=FORM_RULE_FAILED,
            errors=[
                {"field": f"rules[{i}]", "msg": rule.message.get("en") or rule.message["de"]}
                for i, rule in blocking
            ],
        )


async def check_internal_cost_centres(
    session: AsyncSession,
    effective: EffectiveFormOut,
    data: Mapping[str, Any],
    *,
    changed: frozenset[str] | None = None,
) -> None:
    """Refuse an answer of a ``budget_select`` field that names an Intern cost center (003012).

    ``changed`` works as in `check_form_rules`: an edit checks only the fields it changed,
    because an older answer can name a cost center that became Intern later.

    Raises:
        ValidationProblem: 422 ``cost_centre_internal`` with the fields.
    """
    picked = tuple(
        (bid, f.key)
        for section in effective.sections
        for f in section.fields
        if f.type == "budget_select" and (changed is None or f.key in changed)
        if (bid := _uuid_or_none(data.get(f.key))) is not None
    )
    internal = await internal_ids(session, (bid for bid, _key in picked))
    if internal:
        raise ValidationProblem(
            "The cost centre is internal.",
            code=COST_CENTRE_INTERNAL,
            errors=[
                {"field": key, "msg": "the cost centre is internal"}
                for bid, key in picked
                if bid in internal
            ],
        )


def _uuid_or_none(value: object) -> uuid.UUID | None:
    """Return the answer as a UUID, or None when it is empty or no UUID."""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
