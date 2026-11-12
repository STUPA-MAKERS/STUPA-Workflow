---
id: "000680"
title: A script writes the generated UML views, and CI checks that they are current
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "backend/tests/unit/scripts/test_build_uml.py:test_views_are_written_with_the_same_bytes"
  - "backend/tests/unit/scripts/test_build_uml.py:test_committed_views_are_current"
implementation:
  - scripts/build_uml.py
  - .github/workflows/ci.yml
scope:
  - specs/
  - scripts/
  - .github/workflows
---

# A script writes the generated UML views, and CI checks that they are current

The script `scripts/build_uml.py` must write the views `components.json`, `classes.json` and
`deployment.json` from the code. Nobody must edit these three files by hand. The script must
write the same bytes for the same code: sorted keys, sorted elements and edges, two spaces of
indent, and a newline at the end.

`scripts/build_uml.py --write` must write the files. `scripts/build_uml.py --check` must fail
when a written file differs from the file that the script would write now. The CI job `specs`
must run `--check`. A change of a model, a module import or a compose service must also commit
the new files.

Reason: A diagram that a person draws is wrong after the next change. A diagram that CI
compares with the code is always true.

Test: The CI job `specs`, and a unit test that runs the script two times and compares the bytes.
