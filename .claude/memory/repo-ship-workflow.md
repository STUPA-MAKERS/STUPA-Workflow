---
name: repo-ship-workflow
description: "This repo — always finish work by branch+commit+push+PR, then watch CI and fix failures"
metadata: 
  node_type: memory
  type: feedback
---

For the antragsplattform repo, when work is done: create a new branch, commit, push, open a PR — then watch CI and fix any failures, without being asked each time. This is a standing default.

**Why:** User stated "always for this repo" on 2026-06-18. They never want to manually ask for the ship steps.

**How to apply:** Remote is `stupa` → github.com/STUPA-MAKERS/STUPA-Workflow. Use `gh` for PR + CI watch (`gh pr checks --watch` / `gh run watch`). Branch off main (default branch). End commit msg with the Co-Authored-By trailer. See [[antragsplattform-backlog]].
