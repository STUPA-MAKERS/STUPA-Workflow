import type { BadgeVariant } from '@shared/ui/badge/badge.component';
import type { ScanState } from '@core/api/models';

/**
 * Anzeige-Titel eines Antrags aus den freien `data`-Feldern ableiten. Forms
 * haben kein garantiertes `title`-Feld; wir nehmen den ersten nicht-leeren
 * String aus den üblichen Schlüsseln, sonst den Fallback (i18n „Ohne Titel“).
 */
export function applicationTitle(
  data: Record<string, unknown> | null | undefined,
  fallback: string,
): string {
  if (!data) return fallback;
  for (const key of ['title', 'name', 'subject', 'titel']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return fallback;
}

/**
 * Diff-/Daten-Feldwerte robust für die Anzeige stringifizieren: Skalare direkt,
 * Objekte/Arrays als kompaktes JSON, `null`/`undefined` als leerer String.
 */
export function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

/** Scan-Zustand → Badge-Variante: läuft = warnend, bereit = grün, Befund = rot. */
export function scanBadgeVariant(state: ScanState): BadgeVariant {
  switch (state) {
    case 'clean':
      return 'success';
    case 'quarantined':
      return 'danger';
    case 'scanning':
      return 'warning';
    default:
      return 'neutral';
  }
}

/** Bytes menschenlesbar (binär, 1 Nachkommastelle ab KB). `0` → „0 B". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}
