---
id: "000040"
title: Schemas use the shared camelCase base model
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
---

# Schemas use the shared camelCase base model

A Pydantic schema of the API must use the camelCase base model of `app/shared/config_schemas.py`.
An input schema must refuse unknown fields (`extra="forbid"`).
