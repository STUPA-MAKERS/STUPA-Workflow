---
id: "000051"
title: Commits are unsigned and have no trailers
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - .
---

# Commits are unsigned and have no trailers

Make commits with `git -c commit.gpgsign=false commit`. A commit message must not have a
`Co-Authored-By` trailer or any other attribution trailer.
