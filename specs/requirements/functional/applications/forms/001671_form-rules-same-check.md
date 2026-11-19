---
id: "001671"
title: Frontend and backend check the same form rules
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# Frontend and backend check the same form rules

The form must check each rule of 001670 while the applicant types and at the submit. A rule
with `block` whose expression is false must block the submit and show its message. A rule with
`warn` must show its message and must not block. The backend must check the same rules with the
same evaluator. It must refuse an Antrag that breaks a `block` rule with 422
`form_rule_failed`.

Reason: A check that only the frontend makes can be passed by a direct API call, and two evaluators can disagree.

Test: A shared fixture of rules and answers runs in a backend unit test and in a frontend unit test with the same results.
