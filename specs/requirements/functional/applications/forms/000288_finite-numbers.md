---
id: "000288"
title: Numbers are finite decimals
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# Numbers are finite decimals

A number answer must become a `Decimal`. NaN and Infinity must be refused.
