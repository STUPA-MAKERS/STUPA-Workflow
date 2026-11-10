---
id: "000642"
title: A CI ratchet lowers the fake sessions in tests
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/tests
  - scripts/
  - .github/workflows
---

# A CI ratchet lowers the fake sessions in tests

A script must count the classes in `backend/tests/unit` that stand in for a database session,
per file, against a stored baseline. A class counts when its name contains `Session`. CI must
fail when the count of a file goes up. A file that is not in the baseline must have the count 0.
A change that lowers the count must also lower the baseline.

Reason: The rule 000641 holds for new tests at once, and the existing tests stay until an
integration test replaces them.

Test: The CI job `functional`.
