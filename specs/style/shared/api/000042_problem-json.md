---
id: "000042"
title: Every error is problem+json
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
---

# Every error is problem+json

Every 4xx and 5xx answer must be `application/problem+json` (RFC 9457), also in a new branch.
Use `app/shared/errors.py`. Do not return a bare string or the default `detail` of FastAPI.
A conflict carries a machine-readable `code`, for example `vote_not_deletable`.
