---
id: "000628"
title: The branches development and main require the CI checks
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
implementation: null
scope:
  - .github/workflows/ci.yml
---

# The branches development and main require the CI checks

The branches `development` and `main` must have a branch protection. The protection must
require the check `ci-ok` of `ci.yml` (001244). The
protection must refuse a direct push and a force push. Only the owner must be able to change
the protection or to bypass it.

Reason: A check that is not required can be red at the merge. `ci-ok` needs every job, so one
required check covers the jobs that run and the jobs that are skipped (001240). The integration tests and the
migration test are the only checks that run on a real database.

Test: Review of the branch settings of the repository.
