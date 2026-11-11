---
id: "000583"
title: An applicant logs in with an e-mail link
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/applications/email_login.py
  - backend/app/modules/applications/login_router.py
  - backend/app/modules/applications/router.py
  - backend/app/modules/applications/captured_mail.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
  - backend/app/modules/notifications
  - frontend/src/app/features/apply
---

# An applicant logs in with an e-mail link

A person must be able to request a login link for an e-mail address on the public website. The
link must open an applicant session for that address. The session must read and edit every
Antrag whose applicant e-mail is the address, compared case-insensitively. In each Antrag the
session must have the same rights as an applicant session (`F/administration/accounts/000269`).

The mail after a new Antrag and the mail after a capture must send this login link, not a link
for the one Antrag. A link for one Antrag that was sent before must keep working and must open
the same view (`F/applications/applications/000588`).

Reason: An applicant files several Anträge over time. Each Antrag had its own link in its own
mail, and an old mail gets lost. One login for the address finds them all.

Test: `backend/tests/integration/modules/auth/test_email_login.py`: a session of the address reads and edits two
Anträge of the address and gets 403 for an Antrag of another address; the submit mail carries a
login link.
