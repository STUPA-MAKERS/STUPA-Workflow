---
id: "000290"
title: An audit entry holds no personal data
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/audit
  - backend/app/modules/
scope:
  - backend/app/modules/audit
  - backend/app/modules/
---

# An audit entry holds no personal data

The `data` of an audit entry must hold only ID references and metadata. It must not hold names,
e-mail addresses, IP addresses, guest names, join codes or Markdown texts. The one exception is
`pii_export`: its `target_id` is the e-mail address of the data subject.

Reason: Art. 30 DSGVO needs proof of whose data left the platform.
