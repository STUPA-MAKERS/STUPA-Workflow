import { Injectable } from '@angular/core';
import { DefaultUrlSerializer, UrlTree } from '@angular/router';

/**
 * The old German path prefixes and their English paths (spec 000592). A prefix matches a
 * whole path segment: `/gremien` matches `/gremien` and `/gremien/g-1`, not `/gremienx`.
 */
export const LEGACY_PATHS: readonly (readonly [string, string])[] = [
  ['/antrag', '/my-applications'],
  ['/protokolle', '/protocols'],
  ['/barrierefreiheit', '/accessibility'],
  ['/gremien', '/committees'],
  ['/admin/gremien', '/admin/committees'],
  ['/voting/beamer', '/voting/projector'],
];

/** The old German query keys and their English keys. */
export const LEGACY_QUERY_KEYS: Readonly<Record<string, string>> = {
  gremium: 'committee',
  ks: 'costCentre',
};

/** The old German values of `?tab=` on a committee and their English values. */
export const LEGACY_TAB_VALUES: Readonly<Record<string, string>> = {
  sitzungen: 'meetings',
  mitglieder: 'members',
  anwesenheit: 'attendance',
  beschluesse: 'decisions',
};

/** Split a URL into its path and the rest (`?query` and `#fragment`). */
function splitPath(url: string): readonly [string, string] {
  const i = url.search(/[?#]/);
  return i < 0 ? [url, ''] : [url.slice(0, i), url.slice(i)];
}

/** The English path for an old German path, or the path itself. */
export function englishPath(path: string): string {
  const hit = LEGACY_PATHS.find(([old]) => path === old || path.startsWith(`${old}/`));
  return hit ? hit[1] + path.slice(hit[0].length) : path;
}

/** The query parameters with every old German key and tab value in English. */
export function englishQuery(
  params: Readonly<Record<string, string | readonly string[]>>,
): Readonly<Record<string, string | readonly string[]>> {
  return Object.fromEntries(
    Object.entries(params).map(([key, value]) => {
      const newKey = LEGACY_QUERY_KEYS[key] ?? key;
      const newValue =
        key === 'tab' && typeof value === 'string' ? (LEGACY_TAB_VALUES[value] ?? value) : value;
      return [newKey, newValue];
    }),
  );
}

/**
 * The URL serializer of the app. It reads an old German URL as its English URL, so an old
 * link in a mail, a bookmark or a QR code opens the English route with the same ID, query and
 * fragment (spec 000592). The router then writes the English URL into the address bar.
 *
 * `/status?app=<id>&t=<token>`, the old status page of one Antrag, reads as
 * `/my-applications/<id>#t=<token>`; `/status` alone reads as `/my-applications`.
 */
@Injectable()
export class LegacyUrlSerializer extends DefaultUrlSerializer {
  override parse(url: string): UrlTree {
    const tree = super.parse(this.rewritePath(url));
    return new UrlTree(
      tree.root,
      englishQuery(tree.queryParams as Readonly<Record<string, string | readonly string[]>>),
      tree.fragment,
    );
  }

  private rewritePath(url: string): string {
    const [path, rest] = splitPath(url);
    if (path === '/status' || path === 'status') return this.rewriteStatus(rest);
    return englishPath(path) + rest;
  }

  private rewriteStatus(rest: string): string {
    const old = super.parse(`/status${rest}`);
    const app = old.queryParams['app'] ?? old.queryParams['id'];
    const token = old.queryParams['t'] ?? null;
    const target = typeof app === 'string' && app ? `/my-applications/${app}` : '/my-applications';
    const fragment = typeof token === 'string' && token ? `t=${token}` : old.fragment;
    return fragment ? `${target}#${fragment}` : target;
  }
}
