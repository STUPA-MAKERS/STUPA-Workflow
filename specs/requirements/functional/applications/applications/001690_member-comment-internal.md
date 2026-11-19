---
id: "001690"
title: A member comment is internal by default
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A member comment is internal by default

The comment field of an Antrag must preselect `Intern` for a person who may write an internal
comment. Each new comment must start with this choice. For the applicant the comment stays
public.

Reason: Prod data holds 89 of 107 member comments as public, and 5 of them were clearly meant to be internal. A wrong internal comment can be fixed, a wrong public one sends a mail at once.

Test: A frontend unit test opens the comment field as a member and as the applicant.
