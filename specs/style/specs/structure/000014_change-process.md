---
id: "000014"
title: A change goes through a pull request
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - specs/
scope:
  - specs/
---

# A change goes through a pull request

A change to a spec must follow these steps:

1. Find the topic folder. If there is none, make it. 2. Copy the template. Give the rule the
highest number in `specs/` plus one. 3. Set `status: draft` and set `updated` to the current
date. 4. Update the index. 5. Open a pull request. The owner sets `approved`.
