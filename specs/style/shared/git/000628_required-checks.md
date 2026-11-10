---
id: "000628"
title: The branches development and main require the CI checks
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - .github/workflows/ci.yml
---

# The branches development and main require the CI checks

The branches `development` and `main` must have a branch protection. The protection must
require these checks of `ci.yml`: `specs`, `functional`, `be-lint`, `be-typecheck`, `be-unit`,
`be-integration`, `be-contract`, `be-migrations`, `coverage-gate`, `fe-unit` and `axe`. The
protection must refuse a direct push and a force push. Only the owner must be able to change
the protection or to bypass it.

Reason: A check that is not required can be red at the merge. The integration tests and the
migration test are the only checks that run on a real database.

Test: Review of the branch settings of the repository.
