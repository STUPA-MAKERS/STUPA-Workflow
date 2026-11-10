---
id: "000640"
title: A CI ratchet lowers the commits in services
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app
  - scripts/
  - .github/workflows
---

# A CI ratchet lowers the commits in services

A script must count the `commit()` calls in `backend/app` outside the router files, per file,
against a stored baseline. CI must fail when the count of a file goes up. A file that is not in
the baseline must have the count 0. A change that lowers the count must also lower the baseline.

Reason: The rule 000474 holds for new code at once. The old calls move to the routers module by
module, and the baseline shows what is left.

Test: The CI job `functional`.
