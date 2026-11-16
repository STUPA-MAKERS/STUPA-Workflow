---
id: "000886"
title: The public Anlage blacks out the personal data
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
implementation:
  - backend/app/modules/protocol
  - backend/app/modules/documents
scope:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
  - backend/app/modules/applications
  - backend/app/modules/documents
  - typst
---

# The public Anlage blacks out the personal data

In the public PDF, the Antrag Anlage must show the answers of each field with `is_pii`, the
name and the e-mail of the applicant as a black bar, the same way as a marked segment (000685).
The internal PDF must show them in full. The public protocol page must not show the Antrag
Anlage: it is only in the PDF.

Reason: A public protocol has no names (000172). The applicant is often a private person.

Test: Unit test of the Markdown builder for the public variant: no PII answer and no applicant
name is in the text.
