import { test } from '@playwright/test';

/**
 * Szenarien 3 + 4 (testing.md §3.3/§3.4): asynchrones Voting und **Live-Vote** mit
 * zwei Browser-Contexts + Beamer-Sicht (Live-Balken + Quorum, KEINE Namen).
 *
 * Tier `@full` (opt-in, NICHT gate-bindend) — Frederiks Regel „lieber stabil als
 * flaky": die WS-Live-Vote-Pfade (Redis-PubSub-Fan-out, parallele Casts, Timing)
 * sind im CI-Runner nicht zuverlässig deterministisch und brauchen zusätzliche
 * Fixtures (offene Sitzung, Stimmberechtigte). Lauf via `scripts/e2e.sh --full`.
 *
 * Status: bewusst `fixme` (dokumentierter Grund, kein stiller skip — testing.md §6).
 * Aufbau, sobald eine deterministische Live-Vote-Seed-Fixture (Meeting + offener
 * Vote + 2 stimmberechtigte Principals) steht. Abzudeckende Schritte:
 *   1. Admin/Manager öffnet Sitzung + Vote live (`/voting/meeting/:id`).
 *   2. Zwei Applicant-/Member-Contexts geben mobil ab (`/voting/vote/:id`).
 *   3. Beamer (`/voting/beamer/:id`) zeigt Live-Balken + Quorum, KEINE Namen.
 *   4. Schließen → Ergebnis (passed/failed) in allen Sichten konsistent.
 */
test.describe('@full Live-Vote (WS, 2 Contexts + Beamer)', () => {
  test.fixme(true, 'Opt-in/non-gating: deterministische Live-Vote-Fixture ausstehend (siehe PR-DoD).');

  test('async Vote: anlegen → öffnen → abstimmen → schließen → Branch', async () => {
    // TODO(T-40-full): Vote-Seed + UI-Treiber.
  });

  test('Live-Vote: 2 Contexts abstimmen, Beamer zeigt Balken+Quorum ohne Namen', async () => {
    // TODO(T-40-full): Meeting/Beamer-Seed + WS-Sync-Assertions.
  });
});
