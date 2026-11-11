---
id: "000648"
title: The module notifications holds the mail engine only
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
scope:
  - backend/app/modules
  - backend/pyproject.toml
---

# The module notifications holds the mail engine only

The module `notifications` must hold only the mail engine: the templates and their catalogue,
the layout, the links, the queue, the send, the mail preferences, and the recipient search by
group, role, committee, permission and address. It must import no module of a higher layer.

The code that builds the mail of one subject must be in the module that sends this mail. The
ticket mails are in `tickets`, the to-do mails are in `todos`, the poll mails are in `voting`,
the mails about comments, mentions and captured Anträge are in `applications`, the delegation
mails are in `delegations`, the meeting mails are in `livevote`, and the erasure mails are in
`privacy`. The flow action that sends a mail and the search for the persons who can act on an
Antrag are in `flow`. When a lower module starts a mail of a higher module, the lower module
builds this mail from its own data.

The import contract must have no exception for an import from `notifications`.

Reason: `notifications` is in layer 4, and the modules of the layers above send their mails
through it. When the mail engine reads the models of these modules, each of them imports its
own importer, and a change to one mail can break all the others.

Test: A unit test reads the import contract in `backend/pyproject.toml` and finds no exception
that starts with `app.modules.notifications`.
