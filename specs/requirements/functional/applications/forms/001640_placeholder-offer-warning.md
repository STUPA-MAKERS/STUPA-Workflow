---
id: "001640"
title: The form warns about a placeholder offer
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# The form warns about a placeholder offer

The form must show a warning at an offer of a position when one of these conditions is true:

- the value of the offer is 0 € or 1 €,
- the label of the offer has fewer than 3 characters after trimming,
- two or more offers of the same position have the same label, compared without case and
  without leading or trailing spaces.

When the field allows the opt-out (`allowNoOffers`, 000134), the warning must name the switch
`Für diese Position sind keine Vergleichsangebote möglich`
(`No comparison offers are possible for this position`).

Reason: Prod data holds 8 Anträge with offers such as `x`, `000` or `wird nachgereicht`. The applicants did not use the opt-out.

Test: A frontend unit test checks each condition and the text with and without `allowNoOffers`.
