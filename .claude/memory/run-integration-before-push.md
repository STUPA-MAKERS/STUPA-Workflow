---
name: run-integration-before-push
description: A plain pytest deselects the integration tests, and they share one Postgres. Run pytest -m integration before a push
metadata:
  node_type: memory
  type: feedback
---

Run `pytest -m integration` before you push backend work. `backend/pyproject.toml` sets
`addopts = "-m 'not integration and not e2e'"`, so a plain `pytest` **deselects** every
integration test, and a green local run says nothing about them. The integration tests need
Docker (testcontainers); without it they skip.

**Why:** the integration suite shares ONE Postgres container for the whole session
(`tests/integration/conftest.py`). A new test that writes rows another test counts passes alone
and fails in CI. Example: `test_oauth_code_double_spend` counts every token row of the real
MCP client id to prove that a replayed authorization code mints no second token family. A
test that mints tokens under that same client id makes it fail. That is why
`test_oauth_admin_revoke.py` uses a client id of its own.

**How to apply** (from `backend/`):

    nix develop ..#backend -c bash -c '. .venv/bin/activate; python -m pytest -q'                 # unit, integration deselected
    nix develop ..#backend -c bash -c '. .venv/bin/activate; python -m pytest -q -m integration'  # the rest

A new integration test that creates rows keyed by a shared constant (a client id, a slug, a
name) must use a value of its own. Do not widen another test's assertion to make room — that
removes the guarantee the assertion exists for. See [[nix-dev-shells]].
