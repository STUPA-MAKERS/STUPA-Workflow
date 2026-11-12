---
id: "000679"
title: The UML data of the app is in specs/uml
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "backend/tests/unit/scripts/test_build_uml.py:test_format_finds_unknown_edge_ends_and_double_ids"
implementation:
  - scripts/build_uml.py
  - specs/uml
scope:
  - specs/
  - scripts/
---

# The UML data of the app is in specs/uml

The UML data of the whole app must be in the folder `specs/uml/`, one JSON file for each view:

| File | View | Source |
| --- | --- | --- |
| `components.json` | Component diagram of the backend modules (000681) | generated |
| `classes.json` | Class diagram of the database models (000682) | generated |
| `deployment.json` | Deployment diagram of the compose stack (000683) | generated |
| `states/<name>.json` | State diagram of one life cycle (000684) | written by hand |

Each file must have the keys `view`, `title` and `elements`, and a file with lines between the
elements must also have `edges`. Each element must have an `id` that is unique in its file, a
`name`, and a `path`: the file or folder in the repository that holds the element. An edge must
have `from` and `to`, which are element IDs of the same file. Names and IDs are the names in the
code, in English.

The folder must hold no Markdown file, because `scripts/check_specs.py` reads every Markdown file
below `specs/` as a rule.

Reason: The rules and the model of the app then have one place and one version. A reader of a
ref sees the structure of the code at this ref, and a tool can link an element to the specs
whose scope holds its path.

Test: `scripts/build_uml.py --check` reads every file of the folder against these keys.
