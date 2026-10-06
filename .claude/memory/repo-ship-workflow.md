---
name: repo-ship-workflow
description: "This repo — always finish work by branch+commit+push+PR, then watch CI and fix failures"
metadata: 
  node_type: memory
  type: feedback
---

For the antragsplattform repo, finish work like this: create a new branch, commit, push and open a PR. Then watch CI and fix any failures. Do all of this without being asked each time. This is a standing default.

**Why:** the user stated "always for this repo" on 2026-06-18. They never want to ask for the ship steps.

**How to apply:** the remote is `origin` → github.com/STUPA-MAKERS/STUPA-Workflow. Use `gh` for the PR and the CI watch (`gh pr checks --watch` / `gh run watch`). Branch off `development` and open the PR against `development` (the integration branch). Each merge to `development` deploys the dev site. `main` gets only release merges. End the commit message with the Co-Authored-By trailer. See [[antragsplattform-backlog]].
