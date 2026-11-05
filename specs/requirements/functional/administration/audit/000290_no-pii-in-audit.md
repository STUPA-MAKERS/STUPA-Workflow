---
id: "000290"
title: An audit entry holds no personal data
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/audit
  - backend/app/modules/
---

# An audit entry holds no personal data

The `data` of an audit entry holds only ID references and metadata. It must not hold a name,
an e-mail address, an IP address, a guest name, a join code or a Markdown text.
The one exception is `pii_export`: its `target_id` is the e-mail address of the data
subject.

Reason: Art. 30 DSGVO needs proof of whose data left the platform.
