---
id: "000012"
title: A rule is written in one place
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - specs/
scope:
  - specs/
---

# A rule is written in one place

A rule must be in the topic folder that it controls. A rule that applies to two areas must be
in the area that owns the code. A rule must not be written two times. A reference must use the
rule ID instead.

Reason: Two copies of a rule drift apart.
