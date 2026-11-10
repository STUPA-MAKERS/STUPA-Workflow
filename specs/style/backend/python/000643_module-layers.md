---
id: "000643"
title: A backend module imports only from its layer and from lower layers
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/modules
  - backend/pyproject.toml
  - .github/workflows
---

# A backend module imports only from its layer and from lower layers

The backend modules are in five layers, from the top to the bottom:

1. `admin`, `search`, `privacy`, `backup`, `config_revision`, `calendar`
2. `protocol`, `livevote`, `todos`, `tickets`, `delegations`
3. `voting`, `budget`, `applications`, `flow`
4. `forms`, `application_types`, `notifications`, `webhooks`, `files`, `media`, `translations`,
   `avatars`
5. `gremien`, `audit`, `auth`, `antiabuse`, `pdf`

A module must import only from a module of its own layer or of a lower layer. An import inside
a function counts like an import at the top of the file. A new module must get a layer in this
list.

Reason: When every module can import every other module, no module can be read or tested alone,
and a change in one module can break each of the others. One direction makes the effect of a
change visible: it reaches only the layers above.

Test: The import contract in `backend/pyproject.toml`, which the CI job `be-lint` checks with
`lint-imports`.
