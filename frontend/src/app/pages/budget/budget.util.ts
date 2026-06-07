import type { BudgetStage, BudgetStats, PotUsage } from '@core/api/models';

/**
 * Reine Budget-Statistik-Helfer (DI-frei → in `budget.util.spec.ts` isoliert
 * testbar). Aggregiert die `/budget/stats`-Auslastung zu Kennzahlen, leitet
 * Diagramm-Segmente ab und formatiert Geld/Zahlen lokalisiert.
 *
 * Stufen-Semantik (T-17 `rules.usage_from_stage_sums`):
 * `committed = reserved + approved + paid` (tatsächlich gebundene Mittel),
 * `available = total − committed`, `requested` ist die **Pipeline** (beantragt,
 * noch nicht gebunden) und kann das Total übersteigen (Überzeichnung).
 */

/** Gebundene Stufen (Teil von `committed`) in Anzeige-Reihenfolge. */
export const COMMITTED_STAGES: readonly BudgetStage[] = ['paid', 'approved', 'reserved'] as const;

/** Aggregierte Dashboard-Kennzahlen über alle (gefilterten) Töpfe. */
export interface BudgetKpis {
  potCount: number;
  /** Gemeinsame Währung, falls eindeutig; sonst `''` (Beträge dann gemischt). */
  currency: string;
  mixedCurrency: boolean;
  /** Summe der Topf-Limits; `null`, wenn **kein** Topf ein Limit hat. */
  total: number | null;
  requested: number;
  reserved: number;
  approved: number;
  paid: number;
  committed: number;
  /** Freie Mittel (nur über Töpfe **mit** Limit); `null`, wenn keiner limitiert. */
  available: number | null;
  /** Antragszahl gesamt (Summe der Statusverteilung). */
  applicationCount: number;
}

/** Ein Segment der Auslastungs-Leiste eines Topfs. */
export interface UsageSegment {
  stage: BudgetStage;
  amount: number;
  /** Breite in Prozent des Nenners (Total bzw. committed). */
  pct: number;
}

/** Auslastungs-Aufschlüsselung eines Topfs für die gestapelte Leiste. */
export interface PotUsageBar {
  /** committed-Stufen (paid/approved/reserved), pct relativ zum Nenner. */
  segments: UsageSegment[];
  /** Anteil committed am Nenner (0–100). */
  committedPct: number;
  /** Freier Rest in Prozent (0, wenn kein Limit oder überzeichnet). */
  availablePct: number;
  /** Nenner der Leiste: Topf-Limit, sonst committed (für Verhältnis-Anzeige). */
  denominator: number;
  /** `true`, wenn committed das Limit übersteigt. */
  overcommitted: boolean;
}

export function kpiTotals(stats: BudgetStats): BudgetKpis {
  const pots = stats.pots;
  const currencies = new Set(pots.map((p) => p.currency));
  const mixedCurrency = currencies.size > 1;
  const limited = pots.filter((p) => p.total !== null);

  return {
    potCount: pots.length,
    currency: currencies.size === 1 ? [...currencies][0] : '',
    mixedCurrency,
    total: limited.length ? limited.reduce((s, p) => s + (p.total ?? 0), 0) : null,
    requested: sum(pots, 'requested'),
    reserved: sum(pots, 'reserved'),
    approved: sum(pots, 'approved'),
    paid: sum(pots, 'paid'),
    committed: sum(pots, 'committed'),
    available: limited.length
      ? limited.reduce((s, p) => s + Math.max(0, p.available ?? 0), 0)
      : null,
    applicationCount: stats.statusDistribution.reduce((s, b) => s + b.count, 0),
  };
}

function sum(pots: readonly PotUsage[], key: 'requested' | 'reserved' | 'approved' | 'paid' | 'committed'): number {
  return pots.reduce((s, p) => s + p[key], 0);
}

/**
 * Gestapelte Auslastungs-Leiste eines Topfs ableiten. Nenner ist das Topf-Limit
 * (`total`); fehlt es, wird relativ zu `committed` skaliert (Limit unbekannt).
 */
export function potUsageBar(pot: PotUsage): PotUsageBar {
  const denominator = pot.total !== null && pot.total > 0 ? pot.total : pot.committed;
  const pct = (v: number): number =>
    denominator > 0 ? Math.min(100, (v / denominator) * 100) : 0;

  const segments: UsageSegment[] = COMMITTED_STAGES.map((stage) => ({
    stage,
    amount: pot[stage],
    pct: pct(pot[stage]),
  }));

  const committedPct = pct(pot.committed);
  const overcommitted = pot.total !== null && pot.committed > pot.total;
  return {
    segments,
    committedPct,
    availablePct: pot.total !== null ? Math.max(0, 100 - committedPct) : 0,
    denominator,
    overcommitted,
  };
}

/** Auslastung in Prozent (committed/total); `null`, wenn der Topf kein Limit hat. */
export function usagePercent(pot: PotUsage): number | null {
  if (pot.total === null || pot.total <= 0) return null;
  return Math.round((pot.committed / pot.total) * 100);
}

/** Geld lokalisiert formatieren; `null`/keine Währung → Strich bzw. reine Zahl. */
export function formatMoney(
  value: number | null,
  currency: string,
  locale: string,
): string {
  if (value === null) return '—';
  if (!currency) return formatNumber(value, locale);
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
}
