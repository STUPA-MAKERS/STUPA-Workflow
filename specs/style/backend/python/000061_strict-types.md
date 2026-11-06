---
id: "000061"
title: Inputs are strictly typed
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/pyproject.toml
scope:
  - backend/
---

# Inputs are strictly typed

Use `Enum` or `Literal` for a closed set of values. Validate query, body and path through
Pydantic. Annotate every function fully. Do not use a bare `Any`. basedpyright must report 0
errors.
