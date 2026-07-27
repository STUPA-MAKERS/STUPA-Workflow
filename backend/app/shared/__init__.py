"""Cross-cutting helpers: error contract, paging, i18n.

The package also holds the config schemas and the evaluators. `config_schemas` is
the Pydantic single source of truth and exports JSON Schema. `jsonlogic` is a pure
JsonLogic subset. `guards` is a pure guard and action evaluator. All of them are
declarative and work from a whitelist. None of them uses eval.
"""
