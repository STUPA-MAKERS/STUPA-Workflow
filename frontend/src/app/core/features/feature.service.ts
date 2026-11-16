import { Injectable, computed, signal } from '@angular/core';

/** The features that an admin switches on and off, in the order of the navigation. */
export const FEATURES = [
  'todos',
  'calendar',
  'meetings',
  'voting',
  'budget',
  'invoices',
  'tickets',
] as const;

/** The key of a feature with a switch. */
export type FeatureKey = (typeof FEATURES)[number];

/** The state of each feature, as the server sends it. */
export type FeatureStates = Readonly<Partial<Record<FeatureKey, boolean>>>;

/**
 * The features a feature needs. A feature is off while one of them is off: an invoice
 * books on a Kostenstelle, so `Rechnungen` needs `Budget`.
 */
export const FEATURE_REQUIRES: Readonly<Partial<Record<FeatureKey, readonly FeatureKey[]>>> = {
  invoices: ['budget'],
};

/**
 * The features that are off in the last loaded config, kept in the browser. The service
 * reads them at the next start, so the navigation does not show an entry of a feature that
 * is off until the config has loaded.
 */
const STORE_KEY = 'ap.features.off';

/**
 * The time of the last save of the switches in this browser. The public config answers
 * from the HTTP cache for some minutes, so the next load asks with this value in the
 * address and gets the config after the save.
 */
const SAVED_KEY = 'ap.features.saved';

/** The features that `states` names as off. A feature without an entry is on. */
export function offFeatures(states: FeatureStates | null | undefined): readonly FeatureKey[] {
  return FEATURES.filter((key) => states?.[key] === false);
}

/**
 * The feature switches of the platform, from the public site config.
 *
 * `BrandingService` loads the config and passes the states on. The navigation, the route
 * guard and the pages read {@link isOn}. This is UX only: the server answers 404
 * `feature_disabled` for a feature that is off.
 */
@Injectable({ providedIn: 'root' })
export class FeatureService {
  private readonly _off = signal<ReadonlySet<FeatureKey>>(new Set(readStored()));
  private settle: () => void = () => {};

  /**
   * Resolves when the config has loaded or its load has failed. The route guard waits for
   * it, so a deep link does not open a page of a feature that is off.
   */
  readonly ready: Promise<void> = new Promise<void>((resolve) => {
    this.settle = resolve;
  });

  /** The features that are off. */
  readonly off = this._off.asReadonly();

  /** The state of each feature, for a template. */
  readonly states = computed<Readonly<Record<FeatureKey, boolean>>>(() => {
    const off = this._off();
    return Object.fromEntries(FEATURES.map((key) => [key, !off.has(key)])) as Record<
      FeatureKey,
      boolean
    >;
  });

  /** True while every one of `keys` is on. No key gives true. */
  isOn(...keys: readonly FeatureKey[]): boolean {
    const off = this._off();
    return keys.every((key) => !off.has(key));
  }

  /** Take the states of the config: after the load and after a save of the switches. */
  apply(states: FeatureStates | null | undefined): void {
    const off = offFeatures(states);
    this._off.set(new Set(off));
    store(off);
    this.settle();
  }

  /** Take the states after a save of the switches on this device. */
  saved(states: FeatureStates): void {
    try {
      localStorage.setItem(SAVED_KEY, String(Date.now()));
    } catch {
      /* ignore */
    }
    this.apply(states);
  }

  /** The value that the load of the public config adds to its address, or null. */
  configVersion(): string | null {
    try {
      return localStorage.getItem(SAVED_KEY);
    } catch {
      return null;
    }
  }

  /** The config did not load: keep the stored states and let the guard go on. */
  loadFailed(): void {
    this.settle();
  }
}

function readStored(): readonly FeatureKey[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(STORE_KEY) ?? '[]');
    return Array.isArray(raw) ? FEATURES.filter((key) => raw.includes(key)) : [];
  } catch {
    return [];
  }
}

function store(off: readonly FeatureKey[]): void {
  try {
    if (off.length) localStorage.setItem(STORE_KEY, JSON.stringify(off));
    else localStorage.removeItem(STORE_KEY);
  } catch {
    /* ignore */
  }
}
