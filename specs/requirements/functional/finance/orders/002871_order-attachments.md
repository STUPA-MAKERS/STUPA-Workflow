---
id: "002871"
title: A Bestellung has its own attachments
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/files/service.py
  - backend/app/modules/orders/router.py
  - frontend/src/app/pages/orders/order-files.component.ts
scope:
  - backend/app/modules/files
  - backend/app/modules/orders
  - frontend/src/app/pages/applications
---

# A Bestellung has its own attachments

A Bestellung must take files as its own attachments, for example the confirmation of the order.
The server must bind each file to the Bestellung and not to the Antrag, like a file of a ticket.
The upload must use the scan, the storage and the download of the attachments of the platform. A
person who reads the Bestellung must read its files, and the upload and the delete must need
`order.manage`. The attachments list of the Antrag must not show these files. An applicant
session must not read them. The delete of a Bestellung must delete its files.

Reason: The confirmation of an order belongs to the purchase and not to the text of the Antrag.
It can hold the data of the shop account, so it must not show among the files that the applicant
gave.

Test: A backend integration test uploads a file to a Bestellung, reads it at the Bestellung,
does not find it in the attachments of the Antrag and gets 404 with an applicant session.
