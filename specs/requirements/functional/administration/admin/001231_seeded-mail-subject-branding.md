---
id: "001231"
title: The seeded subject of the access link mail names the branding
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-17
tests:
  - "backend/tests/integration/test_migrations.py:test_the_seeded_magic_link_subject_names_the_platform_by_the_branding"
implementation:
  - backend/migrations/versions/81852f245ccb_magic_link_subject_branding.py
scope:
  - backend/migrations
  - backend/app/modules/notifications
---

# The seeded subject of the access link mail names the branding

A migration must replace the seeded subject of the mail template `magic_link` with the
built-in subject, which names the platform with `{{ platformName }}`. The migration must
change a language only where the subject is still the exact seed text. A subject that an
admin changed must stay as it is.

Reason: The seed put the template into the database with the fixed name "Antragsplattform".
A template in the database wins over the built-in text, so every installation sent the old
name in the subject.

Test: An integration test runs the migration on a seeded subject and on a changed subject,
and back.
