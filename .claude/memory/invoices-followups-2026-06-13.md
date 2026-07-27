---
name: invoices-followups-2026-06-13
description: "Invoices tab follow-up backlog (2026-06-13) — receipt URL, manual attach, centering, booking prefill"
metadata: 
  node_type: memory
  type: project
---

Follow-up requests on the invoices tab (#15), after the fix of the ZUGFeRD parse
timeout and the dialog overflow:

1. **Receipt link shows the internal minio URL** — the presigned download URL
   points at the internal `minio:9000` host, which the browser cannot reach. It
   must use the public endpoint.
2. **Receipt for non-ZUGFeRD invoices too** — a manual invoice must also accept a
   file. The create dialog needs a receipt file picker. A non-ZUGFeRD drop must
   keep the dropped PDF as the attachment.
3. **Center the "no invoices found" empty state** — the table overflow-x breaks
   colspan centering, so the state renders left-aligned. Center it in the viewport.
4. **Booking: select an invoice → prefill the fields** — when the user picks an
   invoice for a booking or expense, take amount, payee and payer, receipt number
   and invoice date from the invoice.

Done on the same day: the ZUGFeRD timeout fix. pycheval `extract_facturx_from_pdf`
loops forever on a file name other than `factur-x.xml`, so we replaced it with our
own pypdf extractor. Also done: a tolerant CII header fallback for strict-validator
rejects, and the dialog grid overflow fix (`min-width:0`). See
[[antragsplattform-backlog]].

5. **Warn about duplicate invoices at import** — on ZUGFeRD import, detect a
   likely duplicate against the existing invoices (same number + supplier, maybe
   same gross). Warn the user before the import creates the invoice.
