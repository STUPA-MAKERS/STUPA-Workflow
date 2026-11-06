---
id: "000288"
title: Numbers are finite decimals
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# Numbers are finite decimals

A number answer becomes a `Decimal`. NaN and Infinity are refused.
