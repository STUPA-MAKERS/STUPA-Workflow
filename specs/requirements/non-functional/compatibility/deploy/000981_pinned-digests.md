---
id: "000981"
title: Images and CI actions are pinned by digest
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - deploy/docker-compose.yml
  - .github/workflows/ci.yml
  - .github/workflows/deps-audit.yml
  - .github/dependabot.yml
scope:
  - deploy/
  - .github/
---

# Images and CI actions are pinned by digest

Each image in a compose file and each base image in a Dockerfile must name its sha256 digest
beside the tag. Each action in a workflow must name a full commit hash, with the version in a
comment. Dependabot must update the digests and the hashes.

Reason: A tag can move to other content. A build then runs code that no person reviewed, and
two builds of one release differ.

Test: `scripts/check_ratchets.py` finds no `image:` and no `FROM` without `@sha256:` and no
`uses:` without a 40-character hash.
