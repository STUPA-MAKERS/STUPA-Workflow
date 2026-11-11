---
id: "000630"
title: A magic link opens one Antrag, a login link opens an address
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/applications/models.py
  - backend/app/modules/auth/email_login.py
scope:
  - backend/app/modules/auth
  - backend/app/modules/applications
  - specs/
---

# A magic link opens one Antrag, a login link opens an address

The term `magic link` must mean only the link that opens one Antrag (`MagicLink`). The term
`login link` must mean only the link of the e-mail login that opens every Antrag of an address
(`EmailLoginLink`). A spec, a docstring and a UI text must not use one term for the other
link. 000268 holds the lifetime of a magic link, and 000585 holds the lifetime of a login
link.

Reason: The two links have different lifetimes and a different reach. A rule that says
"magic link" for both gives two answers to one question.
