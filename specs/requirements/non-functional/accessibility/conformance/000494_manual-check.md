---
id: "000494"
title: Each release has a manual screen reader check
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - specs/
---

# Each release has a manual screen reader check

Before a release tag, a person must do the core tasks with NVDA and Firefox and with
VoiceOver on iOS. The core tasks are: submit an Antrag, log in, vote in a live vote, read a
public protocol. The result must go into the accessibility statement.

Reason: Automated checks find about a third of the WCAG errors. Focus order, names in
context and live announcements need a person.
