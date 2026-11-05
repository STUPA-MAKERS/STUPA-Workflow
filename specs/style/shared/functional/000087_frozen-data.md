---
id: "000087"
title: Data types are frozen by default
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
  - ui-kit
  - mcp/
  - typst/typst_service/
---

# Data types are frozen by default

A data type is immutable unless a write needs it. Python: `@dataclass(frozen=True, slots=True)`,
every Pydantic model with `frozen=True`, fields as `tuple`, `frozenset` or `Mapping`. Only
SQLAlchemy ORM rows stay mutable. TypeScript:
`readonly` fields, `readonly T[]`, `ReadonlySet`, `ReadonlyMap`, `as const`.
