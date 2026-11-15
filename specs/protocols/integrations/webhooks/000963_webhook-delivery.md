---
id: "000963"
title: A webhook delivery is a signed JSON POST
kind: protocol
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
version: 1
media_type: application/json
tests:
  - "backend/tests/unit/protocols/test_webhook_delivery.py:test_transition_delivery_matches_schema"
implementation:
  - backend/app/modules/webhooks/signing.py
  - backend/app/modules/webhooks/service.py
  - backend/app/modules/flow/webhook_actions.py
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/flow/webhook_actions.py
---

# A webhook delivery is a signed JSON POST

The platform must send each webhook delivery in this format to the URL of the webhook. A receiver
must check the signature before it uses the body.

## Transport

| Part | Value |
| --- | --- |
| Medium | HTTPS `POST` to the `url` of the webhook. The platform does not follow a redirect. |
| Direction | From the platform to the receiver. |
| Body | The JSON object with sorted keys, without spaces between the tokens, in UTF-8 without `\u` escapes. |
| `Content-Type` | `application/json` |
| `X-Webhook-Event` | The event name. It is the same as `event` in the body. |
| `X-Timestamp` | The time of the attempt in Unix seconds. Each retry has a new time. |
| `X-Signature` | `sha256=` and the lowercase hex HMAC-SHA256 over `<X-Timestamp>.<body>`, with the secret of the webhook as the key. |
| Answer | A `2xx` answer ends the delivery. The retry rules are in F/integrations/webhooks/000298. |

## Schema

The body must match `000963_webhook-delivery.schema.json`.

## Example

```json
{"applicationId":"3f6c1d2e-8a4b-4c5d-9e6f-7a8b9c0d1e2f","event":"application.transition","statusEventId":"5b8e2f1a-3c4d-4e5f-8a9b-0c1d2e3f4a5b","transitionId":"9d0e1f2a-4b5c-4d6e-9f7a-8b9c0d1e2f3a"}
```

```http
POST /hooks/stupa HTTP/1.1
Content-Type: application/json
X-Webhook-Event: application.transition
X-Timestamp: 1763215200
X-Signature: sha256=<hex>
```

## Compatibility

A receiver must ignore a key that it does not know. A receiver must ignore a delivery with an
`event` that it does not know.

Reason: A receiver outside the platform builds against this format. The timestamp in the
signature stops the replay of an old body under a new time.

Test: A unit test sends a transition through the flow action and validates the body against the
schema.
