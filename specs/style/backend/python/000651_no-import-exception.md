---
id: "000651"
title: The import contract has no exception
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules
  - backend/pyproject.toml
---

# The import contract has no exception

The import contract in `backend/pyproject.toml` must have no entry in `ignore_imports`. A new
entry must not be added.

The code that reads a higher module is in the higher module:

1. The routes of the attachments and the rules that read an Antrag, a ticket or a to-do are
   in the module `attachments` in layer 1. The module `files` keeps the storage, the virus
   scan, the drafts, the model and the operations on one attachment.
2. The Gremien page of a member (the overview, the meetings, the attendance and the decisions
   of a Gremium) is in the module `gremien_overview` in layer 1. The module `gremien` keeps
   the models, the roles and the memberships.
3. The route that asks for the erasure of an Antrag is in `privacy`.
4. The route that serves an image of a public protocol is in `protocol`.
5. The services that write a form version and its revision are in `admin`, like the services
   that write the flow and the site configuration.
6. The flow action that sends a webhook is in `flow`, like the flow action that sends a mail
   (000648).

The module `forms` gets the cost-centre options of a form field through a dependency that the
app wires in. It must not import `budget`.

The move must change no URL and no response.

Reason: With an empty list the layers hold for all code, and the ratchet of 000646 has nothing
left to count. An exception that stays teaches the next change to add one more.

Test: A unit test reads the import contract in `backend/pyproject.toml` and finds no entry in
`ignore_imports`.
