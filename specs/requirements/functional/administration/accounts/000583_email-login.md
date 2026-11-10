---
id: "000583"
title: An applicant without an account logs in with an e-mail link
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
  - frontend/src/app/core/auth
---

# An applicant without an account logs in with an e-mail link

A person must be able to request a login link for an e-mail address on the public website. The
link must open an applicant session for that address. The session must read and edit every
Antrag whose applicant e-mail is the address, compared case-insensitively. In each Antrag the
session must have the same rights as the link of that Antrag (`F/administration/accounts/000269`).
The link of one Antrag must keep working.

Reason: An applicant without an account files several Anträge over time. Each Antrag has its own
link in its own mail, and an old mail gets lost. One login for the address finds them all.

Test: `backend/tests/unit/test_email_login.py`: a session of the address reads and edits two
Anträge of the address and gets 403 for an Antrag of another address.
