---
id: "000745"
title: An Antrag can have observers
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation:
  - backend/app/modules/applications
scope:
  - backend/app/modules/applications
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# An Antrag can have observers

The detail menu of an Antrag must have the entry "Beobachter:innen". It must open a dialog that
lists the observers of the Antrag and adds or removes an observer by e-mail address. An Antrag
must have at most 5 observers.

Only the applicant must add and remove observers: the logged-in creator, an applicant session of
the Antrag (`F/administration/accounts/000583`), and a person with `application.manage`. An
observer must not add or remove observers.

The dialog must not show whether an address belongs to an account
(`NF/security/access/000278`).

Reason: A person who worked on an Antrag, but did not submit it, must be able to follow its
progress. The applicant decides who follows it.

Test: `backend/tests/integration/modules/applications/test_observers.py`: the creator adds and
removes an observer, a sixth observer gets 422, an observer and a member without
`application.manage` get 403.
