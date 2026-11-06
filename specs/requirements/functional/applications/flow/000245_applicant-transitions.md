---
id: "000245"
title: Applicant transitions need actorIsApplicant
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# Applicant transitions need actorIsApplicant

The applicant must be able to fire only a manual transition that `actorIsApplicant` opens. Only
the magic-link applicant and the logged-in creator must be able to use the applicant routes.
Any other person must get 403.
