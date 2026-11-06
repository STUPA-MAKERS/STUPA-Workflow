/**
 * Helpers for the functional style (specs/style/shared/functional).
 *
 * `assertNever` closes an exhaustive `switch` (000086). `toggled`, `withEntry` and
 * `withoutKey` build a new collection instead of changing one in place (000084), so a
 * signal `.update()` gets a pure function (000091).
 */

/** A value that may be absent. */
export type Maybe<T> = T | null | undefined;

/** Closes an exhaustive `switch`: the compiler fails when a case is missing. */
export function assertNever(value: never): never {
  throw new Error(`Unexpected value: ${String(value)}`);
}

/** Returns a new set with `item` added when it is absent and removed when it is present. */
export const toggled = <T>(set: ReadonlySet<T>, item: T): ReadonlySet<T> =>
  new Set(set.has(item) ? [...set].filter((x) => x !== item) : [...set, item]);

/** Returns a new map with `key` set to `value`. */
export const withEntry = <K, V>(map: ReadonlyMap<K, V>, key: K, value: V): ReadonlyMap<K, V> =>
  new Map([...map, [key, value]]);

/** Returns a new record without `key`. */
export const withoutKey = <T extends object, K extends keyof T>(record: T, key: K): Omit<T, K> =>
  Object.fromEntries(Object.entries(record).filter(([k]) => k !== key)) as Omit<T, K>;
