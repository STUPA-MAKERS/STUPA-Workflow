import { test } from '@playwright/test';

/**
 * Szenario 5 (testing.md §3.5): Protokoll → PDF → Versand. Protokoll mit
 * eingebetteter Abstimmung finalisieren, PDF via pytex erzeugen, Mail an Verteiler
 * (mailpit), Nextcloud-Put (Mock).
 *
 * Tier `@full` (opt-in, NICHT gate-bindend): der pytex-Render lädt beim ersten Lauf
 * das tectonic-Bundle (Netzwerk, Minuten) — zu langsam/netzabhängig für ein stabiles
 * PR-Gate. Lauf via `scripts/e2e.sh --full`.
 *
 * Status: bewusst `fixme` (dokumentierter Grund, kein stiller skip — testing.md §6).
 * Abzudeckende Schritte:
 *   1. Protokoll anlegen, Abstimmungs-Snippet einbetten.
 *   2. Finalize → Render-Job (pytex) → PDF-Artefakt (MinIO).
 *   3. Versand-Mail im mailpit-Sink abfangen; Nextcloud-Put (Mock) verifizieren.
 */
test.describe('@full Protokoll → PDF → Versand', () => {
  test.fixme(true, 'Opt-in/non-gating: pytex-tectonic-Bundle-Download zu langsam fürs Gate (siehe PR-DoD).');

  test('Protokoll finalize → pytex-PDF → Mail an Verteiler', async () => {
    // TODO(T-40-full): Protokoll-Seed + Render-Polling + mailpit-Assertion.
  });
});
