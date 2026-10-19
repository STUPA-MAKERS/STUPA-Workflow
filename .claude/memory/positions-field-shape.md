---
name: positions-field-shape
description: "Exact JSON shape of a positions (Kostenaufstellung) answer when you create an application through the MCP or the API"
metadata:
  node_type: memory
  type: reference
---

A form field of type `positions` carries the German label "Kostenaufstellung". When you create
an application (MCP `create_application`, or `POST /api/applications`), the answer of such a
field is an **array of position objects**:

```json
{
  "label": "string (required, non-empty)",
  "offers": [
    { "label": "string (required)", "value": 199.99, "preferred": true },
    { "label": "string", "value": 219.5, "preferred": false }
  ]
}
```

Rules (`_validate_positions` in `backend/app/modules/forms/validation.py`):

- The offer keys are `label` / `value` (a finite number > 0) / `preferred`, **NOT**
  `vendor` / `amount` / `quantity`. Wrong keys give `422 Invalid application data.`
- **Exactly one** offer per position has `preferred: true`.
- At least `minPositions` positions (default 1) and `minOffers` offers per position
  (default 3). The engine caps a field at 200 positions and 50 offers per position.
- A position can skip the comparison offers with `"noOffers": true` and a non-empty
  `"noOffersReason"`, when the field allows it (`allowNoOffers`, on by default). Such a
  position needs exactly one offer.
- The answer key is the form field's `key` (for example `kostenaufstellung`), not the literal
  `positions`.
- The promoted `amount` is the sum of the preferred offer values over all positions
  (`positions_total`); no `isPromoted` flag is needed.
- A form can add one `funding` field ("Beantragte Förderung"): a number > 0, at most the
  cost total. When it is filled in, it is the `amount` instead of the cost total.

A 422 comes back as `application/problem+json` with `errors: [{field, msg}]`, where `field` is
for example `kostenaufstellung[0].offers[0]`. The public create is rate-limited per IP
(`429 Too many application submissions from this IP`).
