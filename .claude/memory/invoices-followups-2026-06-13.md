---
name: invoices-followups-2026-06-13
description: "Invoices tab follow-up backlog (2026-06-13) — beleg URL, manual attach, centering, booking prefill"
metadata: 
  node_type: memory
  type: project
---

Follow-up requests on the Rechnungen/Invoices tab (#15), after fixing the ZUGFeRD
parse timeout + dialog overflow:

1. **Beleg-Link zeigt interne minio-URL** — presigned download URL points at the
   internal `minio:9000` host, unreachable from the browser. Must use the public
   endpoint.
2. **Beleg auch für nicht-ZUGFeRD-Rechnungen** — manual invoices should also be
   able to attach a file. Create dialog needs a "Beleg hinzufügen" file picker;
   non-ZUGFeRD drops should keep the dropped PDF as the attachment.
3. **"Keine Rechnungen gefunden." zentrieren** — empty state is left-aligned
   (table overflow-x breaks colspan centering). Center it in the viewport.
4. **Buchung: Rechnung auswählen → Felder prefillen** — selecting an invoice for
   a booking/expense sets amount, payee/payer (Empfänger/Zahler), Belegnummer,
   Rechnungsdatum from the invoice.

Already done same day: ZUGFeRD timeout fix (pycheval `extract_facturx_from_pdf`
infinite-loops on filenames ≠ `factur-x.xml`; replaced with own pypdf extractor),
tolerant CII header fallback for strict-validator rejects, dialog grid overflow
(`min-width:0`). See [[antragsplattform-backlog]].

5. **Doppelte Rechnungen beim Import verhindern (Warnung)** — on ZUGFeRD import, detect a likely-duplicate (same number + supplier, maybe same gross) against existing invoices and warn the user before creating.
