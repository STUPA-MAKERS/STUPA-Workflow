---
name: run-integration-before-push
description: The unit suite alone cannot catch cross-test pollution. Run `pytest -m integration` before a push
metadata:
  node_type: memory
  type: feedback
---

Run `pytest -m integration` before you push backend work. A plain `pytest` **deselects**
every integration test, so a green local run says nothing about them.

**Why:** the integration suite shares ONE Postgres container across all tests. A new test
that writes rows another test counts will pass alone and fail in CI. That happened on
2026-08-06: a new admin OAuth-revoke test minted tokens under the production client id
`antragsplattform-mcp`, and `test_oauth_code_double_spend` counts every token row of that
client to prove a replayed authorization code mints no second token family. Its assertion
read 3 instead of 1. Both tests pass alone. Only running them together shows it.

**How to apply:**

    nix develop ..#backend -c bash -c '. .venv/bin/activate; python -m pytest -q'                 # unit, integration deselected
    nix develop ..#backend -c bash -c '. .venv/bin/activate; python -m pytest -q -m integration'  # the rest

A new integration test that creates rows keyed by a shared constant (a client id, a slug,
a name) must use a value of its own. Do not widen another test's assertion to make room —
that removes the guarantee the assertion existed for. See [[nix-dev-shells]],
[[repo-ship-workflow]].
