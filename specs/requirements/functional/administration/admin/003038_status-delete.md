---
id: "003038"
title: A status in use is deleted only with a replacement
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/statuses/service.py
  - frontend/src/app/pages/admin/statuses/statuses.component.ts
scope:
  - backend/app/modules/statuses
  - backend/app/modules/orders
  - frontend/src/app/pages/admin
---

# A status in use is deleted only with a replacement

The delete of a status that an element uses must name a replacement status of the same list.
The delete must then set each element with the deleted status to the replacement, and write one
audit entry with the number of the changed elements. Without a replacement the API must answer
409 `status_in_use`. A status that a flow setting names (002931) must not be deleted, and the
API must answer 409 `status_in_flow`.

On the page of the list, the delete button of a status that elements use must open a select
sheet (kit `app-select-sheet`): its heading names the status, its subtitle the number of the
elements, and its rows are the other stored statuses of the list. Only the pick deletes the row
and keeps the replacement for the save; Abbrechen keeps the row. The page must show no field
for the replacement under the list.

Reason: An element must always have a status of its list. The admin decides where the elements
go, and the audit entry tells later why their status changed.

Test: A backend unit test deletes a used status with a replacement and reads the elements in the
replacement, and gets 409 without a replacement. A frontend unit test deletes a used status,
reads the sheet, picks a replacement and reads it in the request; Abbrechen keeps the row.
