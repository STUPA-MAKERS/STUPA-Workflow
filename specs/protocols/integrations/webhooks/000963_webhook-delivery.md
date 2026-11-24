---
id: "000963"
title: A webhook delivery is a signed JSON POST
kind: protocol
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
version: 1
media_type: application/json
tests:
  - "backend/tests/unit/protocols/test_webhook_delivery.py:test_event_delivery_matches_schema"
  - "backend/tests/unit/protocols/test_webhook_delivery.py:test_test_delivery_matches_schema"
implementation:
  - backend/app/modules/webhooks/signing.py
  - backend/app/modules/webhooks/service.py
  - backend/app/modules/webhooks/events.py
  - backend/app/modules/webhooks/catalog.py
scope:
  - backend/app/modules/webhooks
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

**Keys**

| Key | Always | Value |
| --- | --- | --- |
| `event` | yes | The event name from F/integrations/webhooks/002411, or `webhook.test`. |
| `occurredAt` | yes, except in the bodies before this version | The time of the event, ISO 8601 with offset. |
| ID keys | yes | The IDs of the event from the table below. |
| `data` | yes, except in the bodies before this version | An object with exactly the fields the webhook chose for the event (F/integrations/webhooks/002412). It is `{}` when no field is chosen. |

**Fields per event**

A field marked P is personal (F/integrations/webhooks/002413). Names and labels are in the
language of the platform default. An amount is a decimal string with two places, for example
`"125.00"`. A reference to a Gremium, an Antragsart, a status, a cost centre or a Bereich (`area`) is an
object with `id` and `name`. `fromStatus` and `toStatus` of `ticket.status` are status keys, for
example `"done"`. `source` is `help`, `mail` or `team`.

| Event | ID keys | Fields |
| --- | --- | --- |
| `application.created`, `application.updated`, `application.archived` | `applicationId` | `title`, `type`, `gremium`, `status`, `amount`, `currency`, `approvedAmount`, `url`, `applicantName` P, `applicantEmail` P, `answers` P |
| `application.transition` | `applicationId`, `transitionId`, `statusEventId` | the fields of `application.created`, plus `fromStatus`, `toStatus`, `note` P |
| `comment.created` | `commentId`, `applicationId` | `visibility`, `applicationTitle`, `url`, `body` P, `authorName` P |
| `vote.opened` | `voteId` | `question`, `kind`, `gremium`, `meetingId`, `applicationId`, `closesAt`, `url` |
| `vote.closed` | `voteId` | the fields of `vote.opened`, plus `result`, `counts` |
| `meeting.created`, `meeting.started`, `meeting.closed` | `meetingId` | `title`, `gremium`, `date`, `startTime`, `endTime`, `location`, `status`, `url` |
| `protocol.finalized` | `protocolId`, `meetingId` | `meetingTitle`, `gremium`, `finalizedAt`, `publicUrl` |
| `booking.created` | `bookingId` | `kind`, `amount`, `costCentre`, `fiscalYear`, `description`, `applicationId`, `url` |
| `invoice.created` | `invoiceId` | `number`, `supplier`, `grossAmount`, `currency`, `issueDate`, `dueDate`, `costCentre`, `url` |
| `ticket.created` | `ticketId` | `number`, `title`, `area`, `url`, `kind`, `source`, `body` P, `reporterEmail` P |
| `ticket.message` | `ticketId` | `number`, `title`, `area`, `url`, `body` P |
| `ticket.status` | `ticketId` | `number`, `title`, `area`, `url`, `fromStatus`, `toStatus` |
| `webhook.test` | `webhookId` | the fields of each subscribed event, with example values, under the event name |

`counts` holds only the totals of the options, never a single ballot. `url` is the link to the
element in the platform. A receiver needs a login to open it.

## Example

```json
{"applicationId":"3f6c1d2e-8a4b-4c5d-9e6f-7a8b9c0d1e2f","data":{"amount":"125.00","toStatus":{"id":"0c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f","name":"Genehmigt"}},"event":"application.transition","occurredAt":"2026-11-23T09:00:00+01:00","statusEventId":"5b8e2f1a-3c4d-4e5f-8a9b-0c1d2e3f4a5b","transitionId":"9d0e1f2a-4b5c-4d6e-9f7a-8b9c0d1e2f3a"}
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

Test: A unit test lets each catalog event occur with all fields chosen and validates the body
against the schema.
