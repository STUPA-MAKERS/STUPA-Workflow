---
id: "001875"
title: An open-in link is a text button
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/features/gremien/gremium-meetings/gremium-meetings.component.spec.ts:GremiumMeetingsComponent"
  - "frontend/src/app/features/todos/card-detail/todo-card-detail.component.spec.ts:TodoCardDetailComponent"
  - "frontend/src/app/features/public-protocols/public-protocol-detail.component.spec.ts:PublicProtocolDetailComponent"
implementation:
  - frontend/src/app/features/gremien/gremium-meetings/gremium-meetings.component.html
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.html
  - frontend/src/app/features/public-protocols/public-protocol-detail.component.html
scope:
  - frontend/src/app/features
  - frontend/src/app/pages
---

# An open-in link is a text button

A link that opens another page from a section ("In „Sitzungen“ öffnen", "Im Board öffnen",
"Alle Protokolle von …", "Anträge ansehen", "Buchungen ansehen") must be a text button of size
`sm` in a button group (`<a appButton="text" size="sm">` in `app-button-group`). It must have
no arrow icon and no own link style.

Reason: The open-in links were accent text with an arrow, while the buttons beside them were
tonal pills, so the same action had two looks.

Test: the specs of the three components find the link by its role and its name.
