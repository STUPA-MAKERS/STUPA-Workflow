import type { I18nMap } from '@core/api/models';
import type { StatusDate, StatusDef, StatusListKind, StatusPhase, StatusTone } from '@core/api/statuses.service';
import { STATUS_PHASES } from '@core/api/statuses.service';
import type { StatusListBody } from '../admin.models';

/** One row of the editor: a status of the list as the admin edits it. */
export interface StatusRow {
  readonly key: string;
  readonly name: I18nMap;
  readonly tone: StatusTone;
  readonly phase: StatusPhase;
  readonly setsDate: StatusDate | null;
  /** The number of elements with the stored status; 0 for a new row. */
  readonly used: number;
  /** A new row: its key comes from its name at the save. */
  readonly fresh: boolean;
}

/** The draft of one list: its rows and the replacement of each removed status in use. */
export interface ListDraft {
  readonly rows: readonly StatusRow[];
  /** Removed key → kept key, for each removed status that elements have (spec 003038). */
  readonly replacements: Readonly<Record<string, string>>;
}

/** A removed status that elements have: the admin picks where they go. */
export interface Removed {
  readonly key: string;
  readonly name: I18nMap;
  readonly used: number;
}

/** The longest key that the server takes. */
const KEY_MAX = 40;

export function rowOf(status: StatusDef): StatusRow {
  return {
    key: status.key,
    name: status.name,
    tone: status.tone,
    phase: status.phase,
    setsDate: status.setsDate ?? null,
    used: status.used ?? 0,
    fresh: false,
  };
}

export function draftOf(statuses: readonly StatusDef[]): ListDraft {
  return { rows: statuses.map(rowOf), replacements: {} };
}

/** A new row at the end of the list: in the phase `open`, without a name. */
export function newRow(): StatusRow {
  return { key: '', name: {}, tone: 'neutral', phase: 'open', setsDate: null, used: 0, fresh: true };
}

/**
 * The key of a new status from its name: lower case, `ä` → `ae`, every other sign → `_`,
 * a letter first, and a number at the end while the key is taken.
 */
export function keyOf(name: string, taken: ReadonlySet<string>): string {
  const base =
    name
      .toLowerCase()
      .replace(/ä/g, 'ae')
      .replace(/ö/g, 'oe')
      .replace(/ü/g, 'ue')
      .replace(/ß/g, 'ss')
      .normalize('NFKD')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^[^a-z]+|_+$/g, '')
      .slice(0, KEY_MAX - 3) || 'status';
  const free = (n: number): string => (n === 1 ? base : `${base}_${n}`);
  const first = Array.from({ length: 100 }, (_, i) => i + 1).find((n) => !taken.has(free(n)));
  return free(first ?? 100);
}

/**
 * The keys of the rows: the stored key, else one from the name of a new row. A new row
 * never takes a key of the stored list, so a removed status keeps its own key until the
 * save moves its elements.
 */
export function rowKeys(
  rows: readonly StatusRow[],
  lang: string,
  stored: readonly StatusDef[] = [],
): readonly string[] {
  const reserved = [...stored.map((s) => s.key), ...rows.filter((r) => !r.fresh).map((r) => r.key)];
  return rows.reduce<readonly string[]>(
    (keys, row) =>
      row.fresh ? [...keys, keyOf(nameText(row.name, lang), new Set([...reserved, ...keys]))] : [...keys, row.key],
    [],
  );
}

/** The text of a name in the language of the editor, else German. */
export function nameText(name: I18nMap, lang: string): string {
  return name[lang] ?? name['de'] ?? '';
}

/** The stored statuses that the draft no longer holds and that elements have. */
export function removedInUse(stored: readonly StatusDef[], rows: readonly StatusRow[]): readonly Removed[] {
  const kept = new Set(rows.filter((r) => !r.fresh).map((r) => r.key));
  return stored
    .filter((s) => !kept.has(s.key) && (s.used ?? 0) > 0)
    .map((s) => ({ key: s.key, name: s.name, used: s.used ?? 0 }));
}

/** The phases that no row has; a list needs each phase once at least (spec 003035). */
export function missingPhases(rows: readonly StatusRow[]): readonly StatusPhase[] {
  return STATUS_PHASES.filter((phase) => !rows.some((row) => row.phase === phase));
}

/** The list breaks no rule: names, the first status open, each phase, each replacement. */
export function listValid(draft: ListDraft, stored: readonly StatusDef[], lang: string): boolean {
  const keys = new Set(rowKeys(draft.rows, lang, stored));
  return (
    draft.rows.length >= STATUS_PHASES.length &&
    draft.rows.every((row) => nameText(row.name, lang).trim() !== '') &&
    draft.rows[0]?.phase === 'open' &&
    missingPhases(draft.rows).length === 0 &&
    removedInUse(stored, draft.rows).every((r) => keys.has(draft.replacements[r.key] ?? ''))
  );
}

/**
 * The body of the save. The first status is the start status of a new element, and the
 * date applies only to the list of the Bestellungen (spec 003037).
 */
export function bodyOf(
  kind: StatusListKind,
  draft: ListDraft,
  stored: readonly StatusDef[],
  lang: string,
): StatusListBody {
  const keys = rowKeys(draft.rows, lang, stored);
  const removed = new Set(removedInUse(stored, draft.rows).map((r) => r.key));
  return {
    statuses: draft.rows.map((row, i) => ({
      key: keys[i],
      name: Object.fromEntries(Object.entries(row.name).map(([code, text]) => [code, text.trim()])),
      tone: row.tone,
      phase: row.phase,
      start: i === 0,
      ...(kind === 'order' && row.setsDate ? { setsDate: row.setsDate } : {}),
    })),
    replacements: Object.fromEntries(Object.entries(draft.replacements).filter(([key]) => removed.has(key))),
  };
}

/** The draft sends the stored list again. */
export function unchanged(body: StatusListBody, stored: readonly StatusDef[]): boolean {
  const plain = (s: Omit<StatusDef, 'used'>): string =>
    JSON.stringify([s.key, s.name, s.tone, s.phase, s.start, s.setsDate ?? null]);
  return (
    body.statuses.length === stored.length &&
    body.statuses.every((s, i) => plain(s) === plain(stored[i])) &&
    Object.keys(body.replacements).length === 0
  );
}

/** Move a row one place up (-1) or down (1). */
export function moveRow(rows: readonly StatusRow[], index: number, by: -1 | 1): readonly StatusRow[] {
  const to = index + by;
  if (to < 0 || to >= rows.length) return rows;
  return rows.map((row, i) => (i === index ? rows[to] : i === to ? rows[index] : row));
}
