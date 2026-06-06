import type { BadgeVariant } from '@shared/ui/badge/badge.component';

/**
 * Status-Kategorie → Badge-Variante. Die Kategorien sind backend-seitig auf
 * `open|running|closed` beschränkt (flow/models.py `state_category`-Constraint);
 * unbekannte Werte fallen neutral aus.
 */
export function stateBadgeVariant(category: string | null | undefined): BadgeVariant {
  switch (category) {
    case 'open':
      return 'info';
    case 'running':
      return 'warning';
    case 'closed':
      return 'neutral';
    default:
      return 'neutral';
  }
}

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
