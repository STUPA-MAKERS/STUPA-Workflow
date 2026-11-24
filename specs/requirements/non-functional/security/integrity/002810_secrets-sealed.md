---
id: "002810"
title: A secret of an integration is sealed in the database
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/shared
  - backend/app/modules/tickets/models.py
  - backend/app/modules/paperless/models.py
  - backend/app/modules/webhooks/models.py
  - backend/app/modules/notifications/push_models.py
  - backend/app/modules/auth/models.py
scope:
  - backend/app/shared
  - backend/app/modules
  - backend/migrations
---

# A secret of an integration is sealed in the database

The database must hold each secret of an integration only sealed: the IMAP and the SMTP password
of a Postfach, the Paperless token, the secret of a webhook, the private VAPID key and the
calendar token of a person. The platform must seal with AES-256-GCM under the key `SECRETS_KEY`
and must put the version of the key in front of each sealed value. One shared column type in
`app/shared/` must do the sealing, and a module must not seal by itself. A migration must seal
each value that is already stored.

Reason: A read of the database is enough today to log in to each Postfach, to read the archive in
Paperless, and to forge webhook signatures and push messages. A dump, a restored backup or a
leak of a query result must not give these accounts away (002515, 002746).

Test: A unit test stores each of the five secrets and reads the raw column, and expects no plain
value in it. An integration test runs the migration on plain rows and expects sealed rows that
open to the old values.
