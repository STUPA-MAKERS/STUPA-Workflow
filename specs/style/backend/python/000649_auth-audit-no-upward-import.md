---
id: "000649"
title: The modules auth and audit import no higher module
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules
  - backend/pyproject.toml
---

# The modules auth and audit import no higher module

The modules `auth` and `audit` are in the lowest layer, and every other module uses them. They
must import no module of a higher layer. The import contract must have no exception for an
import from `auth` or from `audit`.

`auth` must hold only the identity: the OIDC login, the sessions, the roles and permissions,
and the OAuth tokens. `audit` must hold only the log: the record of an entry, the hash chain,
its verification, and the read of the entries.

Three parts are in a higher module:

1. The login of an applicant (the magic link and the e-mail login, with their routes) is in
   `applications`, because it reads Anträge and starts flow transitions.
2. The admin view of the audit log (its routes, the labels of the targets, and the revert of
   an entry) is in the module `audit_log`, because it reads the models of almost every module.
3. The route `/auth/me` is in the module `account`, because it asks other modules which tabs
   a person can see.

The move must change no URL and no response.

The files of the applicant login must stay in the list of the files with full branch coverage
(000046), because they decide who gets a session.

Reason: A module that every other module imports must not import them back. If it does, no
module can be read or tested alone, and a change in one module can break the login or the
audit log.

Test: A unit test reads the import contract in `backend/pyproject.toml` and finds no exception
that starts with `app.modules.auth` or with `app.modules.audit`.
