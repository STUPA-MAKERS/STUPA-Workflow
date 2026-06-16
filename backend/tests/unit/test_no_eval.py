"""AC (T-05): **kein `eval`/`exec`** in den deklarativen Evaluatoren — statisch geprüft."""

import ast
from pathlib import Path

import pytest

_MODULES = ["jsonlogic.py", "guards.py", "config_schemas.py"]
_SHARED = Path(__file__).resolve().parents[2] / "app" / "shared"


@pytest.mark.parametrize("module", _MODULES)
def test_no_eval_or_exec_call(module: str) -> None:
    tree = ast.parse((_SHARED / module).read_text(encoding="utf-8"))
    forbidden = {"eval", "exec", "compile", "__import__"}
    bad = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in forbidden
    ]
    assert not bad, f"{module} uses forbidden call(s): {bad}"
