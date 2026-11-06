import { HttpParams } from '@angular/common/http';

/** A value of {@link httpParams}. */
export type ParamValue = string | number | boolean | null | undefined | readonly unknown[];

/**
 * HTTP params from a record, in the order of its keys. An array value repeats its key once per
 * entry, `undefined` and `null` add nothing, and any other value is set as its string.
 */
export function httpParams(entries: Readonly<Record<string, ParamValue>>): HttpParams {
  return Object.entries(entries).reduce(
    (params, [key, value]) =>
      value === undefined || value === null
        ? params
        : Array.isArray(value)
          ? value.reduce((p: HttpParams, entry) => p.append(key, String(entry)), params)
          : params.set(key, String(value)),
    new HttpParams(),
  );
}
