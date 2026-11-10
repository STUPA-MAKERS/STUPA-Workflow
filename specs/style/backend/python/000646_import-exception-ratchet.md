---
id: "000646"
title: A CI ratchet lowers the accepted import violations
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/pyproject.toml
  - scripts/
  - .github/workflows
---

# A CI ratchet lowers the accepted import violations

The imports that break 000643 or 000644 at the time of this rule are a list of exceptions in
the import contract. A script must count the entries of this list against a stored baseline. CI
must fail when the count goes up. CI must also fail for an entry that matches no import. A
change that removes an entry must also lower the baseline.

Reason: The rules hold for new code at once. The old imports go one by one, and the list shows
what is left.

Test: The CI job `functional` and the CI job `be-lint`.
