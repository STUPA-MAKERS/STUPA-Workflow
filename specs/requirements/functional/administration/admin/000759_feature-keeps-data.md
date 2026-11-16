---
id: "000759"
title: A switch keeps the data of the feature
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/features/test_features_api.py:test_a_switch_keeps_the_records_and_the_search_follows_it"
implementation:
  - backend/app/modules/site_config/features.py
  - backend/worker/features.py
scope:
  - backend/app/modules
---

# A switch keeps the data of the feature

A switch that goes off must not delete or change a record of the feature. A switch that goes on
again must show the records as they were. The privacy export, the privacy erasure, the account
merge, the retention and the backup must include the records of a feature that is off.

Reason: A switch is a setting and must be reversible without a loss. The duties of data
protection do not depend on what the UI shows.

Test: `backend/tests/integration/modules/features/test_features_api.py` creates a ticket, switches
`Tickets` off and on and reads the same ticket.
