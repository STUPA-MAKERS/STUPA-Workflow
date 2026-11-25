/**
 * The status lists of the elements (`GET /api/statuses/{kind}`, spec
 * F/administration/admin/003035).
 *
 * An admin names the statuses of the Bestellungen and of the Events on the page "Status &
 * Phasen". Each status has a key, a name per language, a tone, a phase and, for a
 * Bestellung, the date that it sets. The code reads the phase of a status and never names a
 * key (003036). The catalog loads each list once and keeps it in a signal, so every view
 * shows the same names and tones.
 */
import { HttpClient } from '@angular/common/http';
import { InjectionToken, Injectable, type Signal, type ValueProvider, type WritableSignal, inject, signal } from '@angular/core';
import { API_BASE_URL, USE_MOCK_API } from '@core/api/api.config';
import type { I18nMap } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { i18nLabel } from '@shared/forms/i18n-text';
import { type StatusKind, skipLoading } from '@stupa-makers/ui-kit';

/** The kinds of element with a status list. */
export type StatusListKind = 'order' | 'event';
/** `open`: the work goes on. `done`: it is done. `void`: the element did not happen. */
export type StatusPhase = 'open' | 'done' | 'void';
/** The tone of a status: the `StatusKind` of the kit. */
export type StatusTone = StatusKind;
/** The date of a Bestellung that a status sets when it is empty (003037). */
export type StatusDate = 'orderedOn' | 'deliveredOn';

export const STATUS_PHASES: readonly StatusPhase[] = ['open', 'done', 'void'];
export const STATUS_TONES: readonly StatusTone[] = ['neutral', 'accent', 'warn', 'error', 'muted'];
export const STATUS_DATES: readonly StatusDate[] = ['orderedOn', 'deliveredOn'];

/** One status of a list. */
export interface StatusDef {
  readonly key: string;
  readonly name: I18nMap;
  readonly tone: StatusTone;
  readonly phase: StatusPhase;
  readonly start: boolean;
  readonly setsDate?: StatusDate | null;
  /** Only in the admin read: the number of elements with the status. */
  readonly used?: number;
}

/** A status list in its order. */
export interface StatusList {
  readonly kind: StatusListKind;
  readonly statuses: readonly StatusDef[];
}

/** The lists of a new installation (003039); the mock API answers them. */
export const DEFAULT_STATUS_LISTS: Readonly<Record<StatusListKind, readonly StatusDef[]>> = {
  order: [
    { key: 'planned', name: { de: 'Geplant', en: 'Planned' }, tone: 'neutral', phase: 'open', start: true },
    {
      key: 'ordered',
      name: { de: 'Bestellt', en: 'Ordered' },
      tone: 'warn',
      phase: 'open',
      start: false,
      setsDate: 'orderedOn',
    },
    {
      key: 'delivered',
      name: { de: 'Geliefert', en: 'Delivered' },
      tone: 'accent',
      phase: 'done',
      start: false,
      setsDate: 'deliveredOn',
    },
    { key: 'cancelled', name: { de: 'Storniert', en: 'Cancelled' }, tone: 'muted', phase: 'void', start: false },
  ],
  event: [
    { key: 'planned', name: { de: 'Geplant', en: 'Planned' }, tone: 'neutral', phase: 'open', start: true },
    { key: 'settled', name: { de: 'Abgerechnet', en: 'Settled' }, tone: 'accent', phase: 'done', start: false },
    { key: 'cancelled', name: { de: 'Abgesagt', en: 'Cancelled' }, tone: 'muted', phase: 'void', start: false },
  ],
};

/**
 * Lists that the catalog holds from the start, without a read: the mock API and the unit
 * tests provide them.
 */
export const STATUS_LIST_SEED = new InjectionToken<Readonly<Record<StatusListKind, readonly StatusDef[]>> | null>(
  'STATUS_LIST_SEED',
  { providedIn: 'root', factory: () => (inject(USE_MOCK_API) ? DEFAULT_STATUS_LISTS : null) },
);

/**
 * The status that follows `key` in the work: the next status of the list that is not in
 * the phase `void`, or null at the end. A status in the phase `void` has no next one.
 */
export function nextStatus(list: readonly StatusDef[], key: string): StatusDef | null {
  const index = list.findIndex((s) => s.key === key);
  if (index < 0 || list[index].phase === 'void') return null;
  return list.slice(index + 1).find((s) => s.phase !== 'void') ?? null;
}

@Injectable({ providedIn: 'root' })
export class StatusCatalog {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);
  private readonly seed = inject(STATUS_LIST_SEED);
  private readonly i18n = inject(I18nService);

  private readonly lists: Readonly<Record<StatusListKind, WritableSignal<readonly StatusDef[]>>> = {
    order: signal(this.seed?.order ?? []),
    event: signal(this.seed?.event ?? []),
  };
  private readonly started: Readonly<Record<StatusListKind, WritableSignal<boolean>>> = {
    order: signal(!!this.seed),
    event: signal(!!this.seed),
  };

  /**
   * The statuses of a list in their order; empty until the first read answers. The first
   * call starts the read in a microtask, because a view calls it inside a `computed`, which
   * must not write a signal.
   */
  list(kind: StatusListKind): Signal<readonly StatusDef[]> {
    if (!this.started[kind]()) queueMicrotask(() => this.start(kind));
    return this.lists[kind].asReadonly();
  }

  /** Read a list again, after a save on the page "Status & Phasen". */
  reload(kind: StatusListKind): void {
    this.started[kind].set(true);
    if (this.seed) return;
    this.http.get<StatusList>(`${this.base}/statuses/${kind}`, { context: skipLoading() }).subscribe({
      next: (list) => this.lists[kind].set(list.statuses),
      error: () => undefined,
    });
  }

  /** Put a list that a save answered, so the views show it at once. */
  set(kind: StatusListKind, statuses: readonly StatusDef[]): void {
    this.started[kind].set(true);
    this.lists[kind].set(statuses);
  }

  find(kind: StatusListKind, key: string | null | undefined): StatusDef | undefined {
    return key ? this.list(kind)().find((s) => s.key === key) : undefined;
  }

  /** The name of a status in the UI language; the key while the list loads or misses it. */
  label(kind: StatusListKind, key: string | null | undefined): string {
    const def = this.find(kind, key);
    return def ? this.name(def) : (key ?? '');
  }

  /** The name of a status in the UI language, else its key. */
  name(def: Pick<StatusDef, 'name' | 'key'>): string {
    return i18nLabel(def.name, this.i18n.uiLocale(), def.key);
  }

  /** The tone of a status; `neutral` while the list loads or misses it. */
  tone(kind: StatusListKind, key: string | null | undefined): StatusTone {
    return this.find(kind, key)?.tone ?? 'neutral';
  }

  /** The phase of a status, or null while the list loads or misses it. */
  phase(kind: StatusListKind, key: string | null | undefined): StatusPhase | null {
    return this.find(kind, key)?.phase ?? null;
  }

  private start(kind: StatusListKind): void {
    if (!this.started[kind]()) this.reload(kind);
  }
}

/** The provider of a unit test: the catalog holds the lists of a new installation. */
export const provideTestStatuses = (
  lists: Readonly<Record<StatusListKind, readonly StatusDef[]>> = DEFAULT_STATUS_LISTS,
): ValueProvider => ({ provide: STATUS_LIST_SEED, useValue: lists });
