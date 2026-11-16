---
id: "000802"
title: Each plan state change is audited
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_each_plan_change_is_audited"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_deletes_name_the_plan_data_that_goes_with_them"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_delete_of_a_budget_names_its_plans"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_plan_entries_keep_the_names_of_what_they_change"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_audit_log_names_a_plan_and_a_budget"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/audit/actions.py
  - backend/app/modules/audit_log/service.py
scope:
  - backend/app/modules/budget
  - backend/app/modules/audit_log
---

# Each plan state change is audited

The platform must write an audit entry for each new version, each deleted version, each
state change of a version, each passed step, each vote created for a step, each change of
the steps of a budget, each change of the plan switch, each state set by hand (000855) and
each change of a line, its side included. The entry must name the Haushaltsplan, the version and the actor. The
entry of a line must hold the Ansatz before and after, the Erläuterung, the Vermerke, the
gesperrt amount and each Ansatz of a parent that the change moved. The entry of a version
that comes into force must hold each allocation that the plan changed, with the amount
before and after. The entry of the plan switch that goes on must name the plans it created. The entry of a delete that takes plan data
along must name that data: the delete of a fiscal year its plan and versions, the delete of
a Kostenstelle its draft lines with the Ansatz of each, and the plan switch that goes off
its deleted versions, and the delete of a top-level Kostenstelle its plans with the
year and the versions of each. The entry of a version must name the budget by its path key
and the year, and the entry of a line the path key and the name of its Kostenstelle. The
entry of a step, of a vote of a step and of a state change must name the budget and the
year too, and the plan switch that goes off the year of each deleted plan. The entry of a
line whose new side takes Vermerke off draft lines (000816) must name those lines with the
path key and the name of their Kostenstelle. The audit log must show a plan as its budget and its
year and a Kostenstelle by its name. A plan action must not be revertable from the audit log.

Reason: An entry that holds only an id cannot be read after the plan is gone. An examiner must be able to see who changed the plan and when. The plan changes
again by a later version or a Nachtrag, so a revert would make a second way around the
steps.

Test: The test runs each plan action and reads the audit entries and their data, and deletes a fiscal year
and a Kostenstelle that hold plan data, and a budget with a plan, and reads the names in the
entries, also in the entry of a step vote. One test reads the labels that the audit log
gives a plan and a Kostenstelle.
