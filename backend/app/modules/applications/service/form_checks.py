"""The checks of an Antrag across fields: form rules and the root of a cost-center field.

`validate_answers` checks one field at a time and has no database. These checks need the
effective form with its rules and with the options that the server injects, so the
create and the edit of an Antrag run them after `validate_answers`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.modules.forms.schemas import EffectiveFormOut
from app.modules.forms.validation import broken_rules, outside_subtree
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ValidationProblem

#: The code of a 422 for an answer that breaks a rule with ``block`` (spec 001671).
FORM_RULE_FAILED = "form_rule_failed"
#: The code of a 422 for a cost center outside the root of its field (spec 001681).
COST_CENTRE_OUTSIDE_SUBTREE = "cost_centre_outside_subtree"


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
