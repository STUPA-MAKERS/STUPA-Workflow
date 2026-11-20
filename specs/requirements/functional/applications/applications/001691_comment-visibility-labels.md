---
id: "001691"
title: The visibility switch names who reads the comment
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/shared/ui/chat/chat.component.ts
  - frontend/src/app/pages/applications/applications-detail.component.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The visibility switch names who reads the comment

The visibility switch of the comment field must have these two options:

- `Intern` (`Internal`),
- `Öffentlich` (`Public`).

The labels have no explanation in brackets.

Reason: The switch is a segment selector, and a long label wraps onto two lines in it. The
solid frame of a public draft (001692) shows that the applicant reads the comment.

Test: A frontend unit test checks the two labels in German and in English.
