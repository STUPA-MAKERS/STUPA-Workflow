---
id: "001691"
title: The visibility switch names who reads the comment
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/shared/ui/chat/chat.component.ts
  - frontend/src/app/pages/applications/applications-detail.component.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The visibility switch names who reads the comment

The visibility switch of the comment field must have these two options:

- `Intern (nur Gremien)` (`Internal (committees only)`),
- `Öffentlich (Antragsteller:in liest mit und bekommt eine Mail)`
  (`Public (the applicant reads it and gets an e-mail)`).

Reason: The words 'intern' and 'öffentlich' alone do not say that a public comment sends a mail to the applicant.

Test: A frontend unit test checks the two labels in German and in English.
