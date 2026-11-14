---
id: "000878"
title: The path key of a Kostenstelle has one hyphen
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/budget/test_budget_tree_rules.py:test_the_path_key_has_one_hyphen"
  - "backend/tests/integration/modules/budget/test_budget_tree_service.py:test_a_path_key_that_another_cost_centre_has_is_refused"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_draft_key_that_gives_a_taken_path_key_is_refused"
  - "backend/tests/integration/test_migrations.py:test_path_keys_take_the_form_with_one_hyphen"
implementation:
  - backend/app/modules/budget/tree_rules.py
  - backend/app/modules/budget/tree/nodes.py
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
---

# The path key of a Kostenstelle has one hyphen

The path key of a Kostenstelle must be the Kürzel of its Haushalt, one hyphen, and then
the keys of each level from the Titel down with nothing between them, for example
`VSM-80133` for the Kostenstelle `33` below the Titel `801` of the Haushalt `VSM`. The
path key of the Haushalt itself is its Kürzel.

The platform must store the path key in this form and show it in every place: the tree,
the plan, the exports, the bookings, the search and the API. The path keys that exist
must take the new form, and also the path keys that a decided plan keeps (000821).

Two Kostenstellen must not have the same path key. A new Kostenstelle, a new key
(000246) and a new key in a draft (000877) that would give a path key that another
Kostenstelle has must be refused with the code `budget_path_key_exists`.

The platform must find the Kostenstellen below a Kostenstelle by their place in the
tree and never by the text of the path key, because `VSM-80133` does not say where one
level ends.

Reason: The Haushaltsplan numbers a Titel and its Kostenstellen as one number, the way
the plans on paper do, and a person types and reads that number.

Test: Unit test: the path key of three levels has one hyphen. Integration tests: a key
that gives the path key of another Kostenstelle is refused, directly and in a draft;
the subtree of `80` does not hold the Kostenstelle `801`. Migration test: path keys and
the lines of a decided plan take the new form.
