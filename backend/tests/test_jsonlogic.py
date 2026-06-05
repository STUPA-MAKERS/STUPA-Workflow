"""TDD: pure JsonLogic-Subset-Evaluator (data-model §5.1). Branch-Coverage-Ziel 100 %."""

import pytest

from app.shared.jsonlogic import (
    JSONLOGIC_OPERATORS,
    JsonLogicError,
    eval_jsonlogic,
    validate_jsonlogic,
)


def test_literals_pass_through() -> None:
    assert eval_jsonlogic(5) == 5
    assert eval_jsonlogic("x") == "x"
    assert eval_jsonlogic(True) is True
    assert eval_jsonlogic(None) is None
    assert eval_jsonlogic([1, 2]) == [1, 2]


def test_var_simple_and_default() -> None:
    assert eval_jsonlogic({"var": "a"}, {"a": 3}) == 3
    assert eval_jsonlogic({"var": "missing"}, {"a": 3}) is None
    assert eval_jsonlogic({"var": ["missing", 99]}, {"a": 3}) == 99


def test_var_dotted_path_and_list_index() -> None:
    ctx = {"a": {"b": {"c": 7}}, "items": [10, 20]}
    assert eval_jsonlogic({"var": "a.b.c"}, ctx) == 7
    assert eval_jsonlogic({"var": "items.1"}, ctx) == 20
    assert eval_jsonlogic({"var": "items.9"}, ctx) is None


def test_var_empty_path_returns_ctx() -> None:
    ctx = {"a": 1}
    assert eval_jsonlogic({"var": ""}, ctx) == ctx
    assert eval_jsonlogic({"var": []}, ctx) == ctx


def test_var_non_string_path_raises() -> None:
    with pytest.raises(JsonLogicError):
        eval_jsonlogic({"var": 5}, {})


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ({"==": [1, 1]}, True),
        ({"==": [1, 2]}, False),
        ({"!=": [1, 2]}, True),
        ({"!=": [1, 1]}, False),
        ({">": [2, 1]}, True),
        ({">=": [2, 2]}, True),
        ({"<": [1, 2]}, True),
        ({"<=": [2, 2]}, True),
        ({">": [1, 2]}, False),
    ],
)
def test_comparison_operators(expr: dict, expected: bool) -> None:
    assert eval_jsonlogic(expr) is expected


def test_logic_and_or_not() -> None:
    assert eval_jsonlogic({"and": [True, True]}) is True
    assert eval_jsonlogic({"and": [True, False]}) is False
    assert eval_jsonlogic({"or": [False, True]}) is True
    assert eval_jsonlogic({"or": [False, False]}) is False
    assert eval_jsonlogic({"not": [False]}) is True
    assert eval_jsonlogic({"not": True}) is False


def test_nested_combination() -> None:
    expr = {"and": [{"==": [{"var": "x"}, 1]}, {"or": [{"<": [{"var": "y"}, 0]}, True]}]}
    assert eval_jsonlogic(expr, {"x": 1, "y": 5}) is True
    assert eval_jsonlogic(expr, {"x": 2, "y": 5}) is False


def test_arithmetic() -> None:
    assert eval_jsonlogic({"+": [1, 2, 3]}) == 6
    assert eval_jsonlogic({"*": [2, 3, 4]}) == 24
    assert eval_jsonlogic({"-": [5, 2]}) == 3
    assert eval_jsonlogic({"-": [5]}) == -5
    assert eval_jsonlogic({"/": [10, 2]}) == 5
    assert eval_jsonlogic({"*": [{"var": "qty"}, {"var": "price"}]}, {"qty": 3, "price": 4}) == 12


def test_in_operator() -> None:
    assert eval_jsonlogic({"in": ["b", ["a", "b"]]}) is True
    assert eval_jsonlogic({"in": ["x", ["a", "b"]]}) is False
    assert eval_jsonlogic({"in": ["ell", "hello"]}) is True


def test_division_by_zero_raises() -> None:
    with pytest.raises(JsonLogicError):
        eval_jsonlogic({"/": [1, 0]})


def test_unknown_operator_raises_not_silent() -> None:
    with pytest.raises(JsonLogicError, match="unknown operator"):
        eval_jsonlogic({"pow": [2, 3]})


def test_multi_key_operation_raises() -> None:
    with pytest.raises(JsonLogicError):
        eval_jsonlogic({"==": [1, 1], "!=": [1, 2]})


@pytest.mark.parametrize(
    "expr",
    [
        {"==": [1]},
        {"!=": [1]},
        {">": [1]},
        {"-": [1, 2, 3]},
        {"/": [1]},
        {"not": [True, False]},
        {"+": []},
        {"*": []},
        {"in": ["x"]},
    ],
)
def test_arity_errors(expr: dict) -> None:
    with pytest.raises(JsonLogicError):
        eval_jsonlogic(expr)


def test_in_non_container_raises() -> None:
    with pytest.raises(JsonLogicError):
        eval_jsonlogic({"in": ["x", 5]})


def test_non_number_arithmetic_raises() -> None:
    with pytest.raises(JsonLogicError):
        eval_jsonlogic({"+": ["a", 1]})
    with pytest.raises(JsonLogicError):
        eval_jsonlogic({">": [True, 1]})


def test_validate_jsonlogic_ok_and_unknown() -> None:
    validate_jsonlogic({"and": [{"==": [{"var": "x"}, 1]}, {"in": ["a", {"var": "list"}]}]})
    validate_jsonlogic(5)  # literal ok
    with pytest.raises(JsonLogicError, match="unknown operator"):
        validate_jsonlogic({"system": ["rm"]})
    with pytest.raises(JsonLogicError):
        validate_jsonlogic({"==": [1], "!=": [2]})


def test_operator_whitelist_is_exact() -> None:
    assert {
        "==", "!=", ">", ">=", "<", "<=",
        "and", "or", "not", "var", "+", "-", "*", "/", "in",
    } == JSONLOGIC_OPERATORS
