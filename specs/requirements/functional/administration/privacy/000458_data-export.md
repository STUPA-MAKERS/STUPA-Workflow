---
id: "000458"
title: The data export is an audited XLSX
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/privacy
scope:
  - backend/app/modules/privacy
---

# The data export is an audited XLSX

`GET /privacy/auskunft` must need `privacy.manage`. It must return all data of one e-mail
address as XLSX and must write `pii_export` with that address as `target_id`.
