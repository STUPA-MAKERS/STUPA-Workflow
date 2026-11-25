---
name: be-orders
description: Bestellungen (orders) of an Antrag — one purchase at one supplier for an approved Antrag of a type with money (purchase_order, purchase_order_event, number B-7K3QX9MD). Covers the kinds Bestellung/Auslage, the statuses planned/ordered/delivered/cancelled, the positions of the Kostenaufstellung by their fixed id, the buyer (account or typed name), the sum against the approved amount (warns, never blocks), the optimistic lock (version, 409 order_version_conflict), the right order.manage, the applicant view, the files of a Bestellung, the audit actions order_* with their revert, the timeline entries of the Antrag, privacy and the account merge, the MCP tools order_* and the frontend page "Bestellungen" (/orders: list, detail and form in the pane). Use when working on backend/app/modules/orders or frontend/src/app/pages/orders.
---

# Bestellungen — `backend/app/modules/orders`

**Does:** Tracks the purchases of an approved Antrag. A Bestellung moves no money: it holds a
planned and a real price, and the bookings stay in `budget`. Only a person creates one, never
a flow action or a status change. The rules are the specs in
`specs/requirements/functional/finance/orders/`.

**Nothing here names a flow state, a transition, a Gremium or an Antragsart.** "Approved" is
the flag `is_approved` of the current state, "with money" is `has_budget` of the type.

**Key files:**
- `models.py` — `PurchaseOrder` (`application_id` CASCADE, `number`, `title`, `kind`,
  `status`, `supplier`, `url`, `order_number`, `position_ids` JSONB, `planned_amount`,
  `actual_amount`, `ordered_on`, `delivered_on`, `buyer_id`, `buyer_name`, `note`, `version`,
  `created_by`) and `ApplicationOrderEvent` (`purchase_order_event`: the events that the
  timeline of the Antrag shows; it outlives the Bestellung, so a delete stays in the story).
- `rules.py` — pure rules: `url_valid` (http/https only), `buyer_missing` (an Auslage needs a
  buyer), `status_dates` (a status sets its date when it is empty), `price` (real, else
  planned), `orders_sum` (without cancelled), `over_by`.
- `numbers.py` — the number `B-` plus eight random characters.
- `service.py` — `OrderService`: list, create, update, set status, delete. It checks the
  approved state and the type with money on create, the positions against the answers of the
  Antrag (unknown id, id of another Bestellung that is not cancelled), the version, and
  writes the audit entry and the timeline event. It does not commit. `buyer_names` gives the
  display name of the buyer accounts.
- `privacy.py` — `erase_buyer`, `clear_buyer_names`, `order_export`.
- `router.py` — the routes; the commit; the files of a Bestellung.

**API surface:**
- `GET /api/applications/{id}/orders` — who reads the Antrag reads its Bestellungen (object
  check, 404 else). Answers `items`, `total`, `approvedAmount`, `overBy`, `canManage`,
  `canCreate`. The applicant view has the number, the Bezeichnung, the kind, the status and
  the two dates only, and null sums.
- `POST /api/applications/{id}/orders` (`order.manage`) — 409 `application_not_approved`,
  422 `application_type_without_budget`, `order_url_invalid`, `order_buyer_required`,
  `order_buyer_unknown`, `order_position_unknown`, 409 `order_position_taken`.
- `GET /api/orders/{id}`, `PATCH /api/orders/{id}` (body with `version`, 409
  `order_version_conflict`), `POST /api/orders/{id}/status`, `DELETE /api/orders/{id}`.
- `GET|POST /api/orders/{id}/attachments`, `DELETE /api/orders/{id}/attachments/{file}` —
  files of the Bestellung (`attachment.order_id`), no attachments of the Antrag. The
  download is the common `/api/attachments/{id}` with the owner kind `order`
  (`attachments/router.py`); an applicant session gets 404.

**Around it:**
- Position ids: `applications/position_ids.py` gives each position of a Kostenaufstellung a
  fixed id on every write and keeps an id that the form sent. Migration `e7d870f703d5`
  backfills the stored answers.
- Audit: `order_create`, `order_update`, `order_status`, `order_delete`
  (`audit/actions.py`), revert in `config_revision/revert.py`.
- Timeline: `applications/service/reads.py` merges the events as entries of kind `order`
  (no price, so the applicant reads the same entry).
- OAuth scope: `budget:write` carries `order.manage`.
- Account merge: `admin/principal_merge.py` lists `buyer_id`, `created_by` and the event
  actor. Privacy: `privacy/service.py` calls the three functions of `privacy.py`.
- MCP: `mcp/antragsplattform_mcp/tools/orders.py` (`order_list`, `order_get`,
  `order_create`, `order_update`, `order_set_status`, `order_delete`, `order_attachments`,
  `order_attachment_upload`, `order_attachment_delete`, `order_list_all`,
  `order_pending_applications`, `order_bookings`, `export_orders_xlsx`).

**Frontend** (`frontend/src/app/pages/orders/`, API in `core/api/orders.service.ts`): the
page "Bestellungen" at `/orders` (nav entry after Rechnungen, feature `orders`,
`ORDER_PERMISSIONS` = `order.manage` or `budget.view`). A Bestellung is an element with a
page of its own; the Antrag detail has no section and no dialog for it.
- `orders-page` — kit `app-list-detail-screen`. The first chip is the segment ("Ohne
  Bestellung" = `GET /orders/pending-applications`, "Offen" (default), "Geliefert",
  "Erledigt" = `GET /orders?segment=`), no counts; chips Haushaltsjahr, Kostenstelle,
  Gremium, Art, "Meine Käufe"; search and chips live in the URL; "Bestellung anlegen" is a
  head action (a FAB would float over the pane), the XLSX export is in the ⋮ menu. A row of
  "Ohne Bestellung" opens its Antrag and has the row action "Bestellung anlegen" (`order.manage`).
- Child routes: `''` (kit `ListNoneComponent`), `new` and `:id/edit` (`order-form`,
  `order.manage`, guard `leaveUnsaved`), `:id` (`order-detail`). The guard `orderAddress`
  leads `/orders?id=<id>` and `/orders?new=order&application=<id>` to the child address.
- `order-detail` — kit `app-detail-screen`: head (Bezeichnung, number, status, marks), the
  next status as the main button, every other action in the ⋮ menu, the fields with the
  signed "Abweichung", the covered positions, the sum of the Antrag with the warning,
  `order-files`, "Verknüpft" (`app-todo-linked-list kind="order"`, built-in rows Antrag,
  invoice, bookings from `GET /orders/{id}/bookings`) and the comments of the Antrag
  (the directive `order-comments` on `app-chat`, in the sheet of the detail as in the Antrag, posts to the comment routes of the Antrag). After "Bestellt" or
  "Geliefert" it asks `GET /applications/{id}/transitions?orderStatus=` and offers the
  transitions in a dialog; nothing fires by itself.
- `order-form` — kit `app-form-screen`. A new Bestellung takes the Antrag from
  `?application=<id>` or from the first field (`pending-applications?withOrders=true`).
  Picked positions fill the planned price (sum of the preferred offers) and, with one
  position, the link (first address in the text of the preferred offer); a typed value
  stays. The account of the buyer is a picker below the form; in an existing Bestellung
  its pick saves at once, because the save button shows only for a dirty form.
- `OrdersRefresh` — the pane tells the list to read again after a write.
- Antrag detail: the Bestellungen are rows of "Verknüpft" (`linkedRows`, link `/orders/<id>`,
  no link in the applicant view) and "Bestellung anlegen" is the button `extra` in its head.
- Flow editor: the setting "Nach einer Bestellung anbieten" of a transition
  (`offerOnOrderStatus`), hidden while the feature `orders` is off.
- `order-files` — list, upload, download and delete of the files.
- `orders.util.ts` — the pure helpers; `orderPositions` finds the positions by their shape,
  because the key of a positions field differs from form to form.
- Timeline text: `shared/decision/timeline-lines.ts` `orderEventText`, used by the Antrag
  detail and by the status page of the applicant.
- Tests: `src/testing/order-fixtures.ts` (`order`, `NO_ORDERS` for a spec that renders the
  Antrag detail).

**Traps:**
- The frontend components have no stylesheet and no class of their own (ratchet
  `app-styles`). The body of the detail gets its vertical gaps from one outer `app-section`
  with a hidden heading.
- The kit list screen renders no row actions, so a row has one target only.
- The empty pane is `order-none.ts`, a re-export of the kit `ListNoneComponent`: a
  dynamic import of a whole kit entry in `app.routes.ts` keeps every export of it in the
  start bundle (it cost 84 kB and broke the 1 MB budget).
- The link kind `order` exists in the kit too (`TodoLinkKind`, `GraphKind`, board texts).
- The table has no check "Auslage needs a buyer": the erasure of an account empties the
  buyer, so the rule lives in the service only.
- A new `AuditAction` needs the frontend list `AUDIT_ACTIONS`, its spec copy and the de/en
  labels.
- A new route needs an MCP tool (route parity test) and, for an object check, an entry in
  `OBJECT_CHECK_ROUTES`.

**Invoice, bookings and marks:**
- `PUT /api/orders/{id}/invoice` (`order.manage` and a budget read permission, body
  `invoiceId` or null and `version`) sets or removes the one invoice of a Bestellung.
  `rules.price_from_invoice` fills an empty real price with the gross amount when no other
  Bestellung names the invoice. The delete of an invoice clears the reference (FK
  `SET NULL`). `GET /api/invoices/{id}/orders` lists the Bestellungen of an invoice; a row
  of an Antrag that the reader does not read has `accessible: false` and no value.
- A booking names a Bestellung with `budget_expense.order_id` (`orderId` of
  `POST /api/expenses`). `budget` is a layer below `orders`, so
  `budget/tree/expenses.py` reads the table `purchase_order` through the metadata and
  never imports the model. 422 `order_application_mismatch` when the booking does not name
  the Antrag of the Bestellung. The delete of a Bestellung with a booking answers 409
  `order_has_bookings` (`ensure_deletable`, asked before the files go).
- `OrderService.marks` reads `invoiceNumber`, `invoiceStatus` and `bookedAmount` at each
  read; the Bestellung stores no copy.
- Frontend: the menu entries "Rechnung verknüpfen" (pick dialog of the detail),
  "Rechnung anlegen" (`/invoices?new=invoice&order=<id>`) and "Buchung anlegen"
  (`/expenses?new=booking&order=<id>`); `bookingRest` and `bookingPayee` give the amount
  and the payee of the booking; the cancel of a booked Bestellung asks first;
  `pages/invoices/invoice-orders` lists the Bestellungen in the invoice detail.

**List, export and the reach into other modules:**
- `listing.py` (`OrderListing`, `OrderFilter`, `segment_clause`) and `list_router.py`:
  `GET /api/orders` (segments `open`, `delivered`, `done`; filters `fiscalYear`, `budget`,
  `gremium`, `kind`, `buyer`, `q`; `limit`/`offset`), `GET /api/orders/pending-applications`
  (approved Anträge of a type with money without a Bestellung that is not cancelled;
  `withOrders=true` keeps those with one, for the form) and `GET /api/orders/export.xlsx`
  (`order.manage`). The listing reads the flag approved of the state, never a state key.
- Link kind `order` (`todos/links.py` `_order_target`), the search source (`search/service.py`
  `_orders`), the graph relations and the webhook events `order.created` and
  `order.status_changed` (`webhook_fields.py`). Every address of a Bestellung is `/orders/<id>`.
- A transition of the flow can carry `offerOnOrderStatus` (`ordered` or `delivered`);
  `GET /api/applications/{id}/transitions?orderStatus=` keeps the transitions with it. The
  platform only offers them; a person creates each Bestellung and fires each transition.

**Related:** `be-applications`, `be-files`, `be-budget`, `be-audit`, `be-privacy`, `mcp`,
`frontend`.

**Feature switch** (§F/finance/orders/003013): `Feature.ORDERS` (`orders`, needs `budget`) in
`site_config/features.py`; `feature_routes.py` closes `/orders`, the Bestellungen of an Antrag and
of an invoice with 404 `feature_disabled`; the link kind and the search source follow it
(`LINK_FEATURE`, `SOURCE_FEATURE`). Frontend: `featureMatch('orders')`, the nav entry, the
Antrag detail and `invoice-orders` read nothing while it is off.

## A Bestellung without an Antrag (spec 003014)

`purchase_order.application_id` is nullable. `POST /api/orders` creates a Bestellung without an
Antrag (`order.manage`), for a purchase from the time before the platform. It has no positions
(422 `positions_need_application`), no approved amount, no sum, no comments and no timeline
entry, because all of these come from the Antrag. `orders/access.py` (`reads_free`) is its read
rule: `order.manage` or `budget.view`, the permissions of the page. `OrderListing._free_filters`
finds it by the Kostenstelle and the Haushaltsjahr of its bookings; the Gremium filter leaves it
out. `GET /api/orders?withoutApplication=true` lists only these. The Antrag of a Bestellung
never changes after the create. A booking sets and removes its Bestellung at the create and at
the change (`ExpenseUpdate.order_id`, spec 002878): both name the same Antrag, or both name none.
Frontend: the first field of the form offers "Ohne Antrag" (`NO_APPLICATION`), and the edit form
of a booking has the field "Bestellung" (`ExpenseDialogsState.loadEditOrders`).
