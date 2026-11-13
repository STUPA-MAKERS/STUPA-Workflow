---
id: "000838"
title: The vote of a plan step runs in a meeting of its Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_step_waits_for_its_gremium_after_the_request"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_plan_vote_opens_only_while_its_step_waits"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_refused_vote_sends_the_version_back_to_the_draft"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_step_of_a_deleted_gremium_takes_no_request"
  - "backend/tests/integration/modules/livevote/test_plan_agenda_vote.py:test_the_agenda_offers_the_waiting_plans_of_its_gremium"
  - "backend/tests/integration/modules/livevote/test_plan_agenda_vote.py:test_the_item_of_a_plan_takes_one_motion_of_the_members"
  - "backend/tests/integration/modules/livevote/test_plan_agenda_vote.py:test_the_vote_of_the_meeting_decides_the_step"
  - "backend/tests/integration/modules/livevote/test_plan_agenda_vote.py:test_a_removed_plan_item_goes_into_another_meeting"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_step_request_and_title"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/plan_router.py
  - backend/app/modules/voting/service.py
  - backend/app/modules/livevote/router.py
  - backend/app/modules/livevote/vote_build.py
  - backend/app/modules/meetings/agenda_service.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - backend/app/modules/voting
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/pages/budget
  - frontend/src/app/features/voting
  - frontend/src/app/features/meetings
---

# The vote of a plan step runs in a meeting of its Gremium

The vote of a plan step must always run in a meeting of the Gremium of the step. A plan
vote without a meeting must not exist, and a plan vote must never open outside a meeting.

A person with `budget.structure` asks for the decision of the next step on the plan page
("Beschluss anfragen", `POST /budget-plan-versions/{id}/steps/next/request`). The request
creates no vote. A draft version must leave the draft with it (000792), and the step then
waits for its Gremium. A step without a Gremium must answer 422 `plan_step_no_gremium`, and a step
that waits already must answer 409 `plan_step_waits`.
The plan page must show for a waiting step that it waits for a meeting of the Gremium, and
after that each meeting that has the plan on its agenda, with a link to it.

A plan step that waits is for its Gremium what an Antrag in a vote state is (000030,
000348). A person who can change the agenda of a meeting of that Gremium (000345) must be
able to add the waiting plan as a TOP, while the meeting is `planned` or `live` (000098).
The action that adds a TOP must offer the waiting plans of this Gremium beside its Anträge,
each with its budget, fiscal year, version and step. The TOP must link the version, show
the plan as its first row with a link to the plan for a person who can read the plan
(000800), and take these four names as its title, which can change (000101). A version
must be on the agenda of a meeting only once. A plan that does not wait for this Gremium
must answer 409 `plan_step_not_waiting`.

The vote of the step is a vote on this TOP. It is prepared, opened, closed, cancelled and
deleted in the meeting in the same way as the vote on an Antrag TOP (000028, 000029): a
motion, secret, with the quorum of the Gremium and the eligible count of the roster
(000381). It must open only while the step waits for the Gremium of the vote, else 409
`plan_step_not_waiting`, and only one vote of a step must be open at a time, else 409
`plan_step_vote_runs`. Only the members of the Gremium must vote on it, never the guests
of the meeting. An election or a poll must not be possible on this TOP. The close
of an accepted vote must pass the step. The close of a vote that is not accepted (refused,
a tie, or without the quorum) must send the version back to the start: each step that the version passed is open again, and the version is a
draft again (000792), so the plan can change and then takes each step again from the first
one. The steps that were passed before stay in the audit log.

The TOP of a plan can be removed under the rules of each TOP (000098). The step then still
waits and can go into another meeting. A version that goes back to the draft no longer
waits: its draft votes go away, and its TOPs stay as TOPs without a vote.

Reason: The Gremium decides on a Haushaltsplan only in a meeting, and the lead of the
meeting sets its agenda. The decision belongs to the agenda and to the protocol of that
meeting.

Test: The backend tests ask for the decision with and without a Gremium, read the plans
that the agenda offers as the lead of a meeting of that Gremium and of another Gremium, add
the TOP to a planned, a live and a closed meeting, add it twice, prepare, open and close
the vote as the protokollant and read the step, open a vote for a step that no longer
waits, remove the TOP and add the plan to another meeting, and move the version back to
the draft. The agenda tests add a plan through the controls and read the first row of its
TOP with and without the read right. The plan page tests read the waiting step and the
link to the meeting.
