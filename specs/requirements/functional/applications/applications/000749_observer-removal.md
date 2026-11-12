---
id: "000749"
title: A removed observer loses the access at once
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation:
  - backend/app/modules/applications
scope:
  - backend/app/modules/applications
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# A removed observer loses the access at once

When the applicant removes an observer, or the observer ends the observation, the next request
of the observer must get 403 for the Antrag. The audit log must record each add and each removal
without the address (`NF/privacy/personal-data/000290`). The anonymization of the Antrag must
delete its observers.

Reason: The applicant must be able to withdraw the access. An address is personal data.

Test: `backend/tests/integration/modules/applications/test_observers.py`: a removed observer gets
403 on the next read; the audit entry has no address; the anonymization leaves no observer row.
