---
id: "000426"
title: Ask with options
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - .
scope:
  - .
---

# Ask with options

An agent must ask the owner a question with concrete options, with the recommended option
first. It must ask one question per decision card: each finding of a report, each open default
and each approval gets its own card, and one card must never hold a group of them. The agent
must send the cards that do not depend on an answer together, and must not wait for one answer
before it sends the next card. It must not end a status reply with open questions in prose.
