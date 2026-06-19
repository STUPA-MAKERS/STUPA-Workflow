---
name: positions-field-shape
description: "exact JSON shape for \"positions\"/Kostenaufstellung form fields when creating applications via MCP"
metadata: 
  node_type: memory
  type: reference
---

When creating an application (MCP `create_application` or API) whose form has a field of type `positions` (German "Kostenaufstellung"), the value is an **array of position objects**. Each position:

```json
{
  "label": "string (required, non-empty)",
  "offers": [
    { "label": "string (req)", "value": 199.99, "preferred": true },
    { "label": "string", "value": 219.5, "preferred": false }
  ]
}
```

Rules (backend `backend/app/modules/forms/validation.py:399` `_validate_positions`):
- Offer keys are `label` / `value` (number > 0, finite) / `preferred` — **NOT** `vendor`/`amount`/`quantity`. Wrong keys → `422: Invalid application data.`
- **Exactly one** offer per position must have `preferred: true` (else "exactly one offer must be marked preferred").
- `minOffers` default 3, `minPositions` default 1 (validation aliases minOffers/minPositions, `config_schemas.py:152`).
- Promoted `amount` = sum of preferred offer values across positions (`positions_total`, no isPromoted flag needed).
- Data key in payload = the form field's `key` (e.g. `kostenaufstellung`), not the literal `positions`.

422 errors come back as `application/problem+json` with `errors: [{field, msg}]` (e.g. `positions[0].offers[0]`).

Verified 2026-06-15 creating VSM "Testantrag" (type key `vsm`). Note: `create_application` is IP-rate-limited (`429: Too many application submissions from this IP`).
