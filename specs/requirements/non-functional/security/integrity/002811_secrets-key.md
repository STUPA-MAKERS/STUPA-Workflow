---
id: "002811"
title: The key of the sealed secrets comes from the deploy
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/settings.py
scope:
  - backend/app/settings.py
  - deploy
---

# The key of the sealed secrets comes from the deploy

The key `SECRETS_KEY` must come from the deploy configuration and must not be in the database or
in a backup. Under `strict_security` the API and the worker must not start without a valid key.
The setting `SECRETS_KEY_OLD` must be able to hold earlier keys, so that a value sealed with an
earlier version still opens and the next write seals it with the current key.

Reason: A key in the same database or backup as the sealed values protects nothing. Without a
way to read the old key, a rotation would lose each stored secret.

Test: A unit test starts the settings under strict security without a key and expects a refusal.
A unit test opens a value of an old key version and expects the value.
