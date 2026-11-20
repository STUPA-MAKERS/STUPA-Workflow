---
id: "001721"
title: A new version links to the old Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/applications/service/links.py
  - frontend/src/app/pages/applications/applications-detail.component.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A new version links to the old Antrag

The new version (001720) must be linked to the old Antrag with the link kind `Neue Fassung von`
(`New version of`). Both Anträge must show the link in `Verknüpft` (`Linked`). The head of the old
Antrag must show `Ersetzt durch` (`Replaced by`) with a link to the new version.

Reason: The reviewer must see the history of an Antrag across its versions.

Test: A frontend unit test renders the head of the old Antrag with the replacement link.
