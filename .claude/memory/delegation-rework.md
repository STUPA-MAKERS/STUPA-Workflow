---
name: delegation-rework
description: "Delegation = sitzungsgebunden (kein Blanko-Zeitraum); Stellvertreter-Pool je Gremium; implementiert im Worktree delegation-feature-audit (2026-06-11, uncommitted)"
metadata: 
  node_type: memory
  type: project
---

Delegations-Feature komplett umgebaut (Spec vom 2026-06-11, Nutzer-Entscheidungen per Frage-Tool):

- **Sitzungsgebunden, nie Blanko-Zeitraum**: `meeting_delegation`-Tabelle (Migration 0014) ersetzt `role_assignment.delegated_by` (Alt-Zeilen zählen fürs Stimmrecht nicht mehr). Genau 1 ausgehende Delegation je (Sitzung, Mitglied); keine Ketten; max. 1 Stimm-Delegation je Empfänger/Sitzung (Transfer ≠ Duplikat).
- **Deadline**: einrichtbar bis `Sitzungsbeginn − gremium.delegation_lead_minutes` (pro Gremium konfigurierbar, Admin-Gremien-Dialog). Widerruf bis Sitzungsbeginn.
- **Stellvertreter-Pool** (`delegation_substitute`, Pflege in Gremium-Mitgliederverwaltung, Perm admin.roles oder Gremium-`session.manage`): gewählte Fachschafts-Vertreter, auch Nicht-Mitglieder; an Pool ohne Vorlauf bis Sitzungsbeginn delegierbar. `member_principal_id NULL` = gremium-weit. Externe Nicht-Pool-Empfänger nur bei `gremium.delegation_allow_external`.
- **Einstiege**: Karte + Dialog auf Sitzungsseite (Follower-View + rechte Spalte), Dashboard-Karte, Admin-Übersicht `/admin/delegations` (jetzt mit Admin-Home-Tile, nur Liste+Widerruf). Voting-UI: Banner „Stimmrecht an X delegiert" + Badge „In Vertretung" (Endpoint `/delegations/votes/{id}/status`).
- Externe Vertreter: WS/Listen-Zugriff via `is_participant`/delegated-meeting-ids; FE-Routen `meetings/:id` + `voting/vote/:id` mit `allowAuthenticated` (Server autoritativ). `delegation_voting_enabled` (global, Default false) gilt weiter; neu `settings.local_timezone` (Europe/Berlin) für Deadline-Berechnung.

Stand: **gemergt in main (13d5a89, fast-forward, 2026-06-11)**, alle Tests/Lint/Typing grün (BE 1371, FE 561); nicht gepusht, Migration 0014 nicht ausgerollt.

**Achtung Kollision:** der unmergte Branch `feat/backlog-audit-mail-pwa-perms` (im Haupt-Checkout ausgecheckt) hat EIGENE Migrationen 0014–0016 (drop_pii / notification_preferences / granular_permissions), alle mit down_revision-Kette ab 0013 → beim Merge entstehen zwei Alembic-Heads + Nummern-Doppelung mit meiner 0014_meeting_delegations. Backlog-Branch muss vor dem Merge renumbern (0015–0017, down_revision 0014_meeting_delegations). Weitere erwartbare Konflikte: translations.ts, tests/test_livevote_service.py (Duplikat-`get`-Fix existiert in beiden), Notification-Mails "delegations" (#4-3) referenzieren ggf. das alte Delegationsmodell. Siehe [[backlog-2026-06-11]], [[admin-domain-rules]].
