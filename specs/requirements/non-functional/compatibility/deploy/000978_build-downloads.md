---
id: "000978"
title: An image build fetches no signing key and repeats a download
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/Dockerfile
  - typst/Dockerfile
  - .github/workflows/ci.yml
scope:
  - backend/Dockerfile
  - typst/Dockerfile
  - deploy/
  - .github/workflows
---

# An image build fetches no signing key and repeats a download

A signing key of a package source must be a file in the repository, and an image build must
not fetch it. Each download in an image build or a CI job must repeat after a failure, at least
three times, and each downloaded binary must pass a sha256 check.

Reason: Production builds its images on the machine at each release. One failed request to
another server then holds the release back, and the same request fails CI runs. A key that the
build fetches is trusted only through TLS.

Test: `scripts/check_build_pins.py` finds no URL of a key in a Dockerfile and no `curl` without
`--retry` in a Dockerfile or a workflow.
