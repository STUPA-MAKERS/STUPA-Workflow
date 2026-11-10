---
id: "000589"
title: Anmelden offers the account login and the e-mail link
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/layout/public-header
  - frontend/src/app/pages
---

# Anmelden offers the account login and the e-mail link

The Anmelden button of the public website must open the page `/login`. The page must offer the
account login and the e-mail link. The name of the account must come from the UI text
`login.accountName`, "STUPA-Konto" by default, which an admin changes under Übersetzungen. The
e-mail form must have ALTCHA and must show the same confirmation for every address.

Reason: A person without an account must find the e-mail login where everybody looks for the
login. The name of the account differs from site to site.

Test: `frontend/src/app/pages/login/login.component.spec.ts`: the page offers both ways, and the
e-mail form shows the same confirmation for every answer 202.
