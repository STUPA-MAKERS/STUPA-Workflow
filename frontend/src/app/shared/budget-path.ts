import { Pipe, type PipeTransform } from '@angular/core';

/**
 * Simplify a path key for display: collapse numeric prefix chains. When a segment
 * is a prefix of the next (8→81→810), only the longest is kept. The top-level
 * segment is always kept. ``VSM-8-81-810-330 → VSM-810-330``.
 *
 * Shared so every cost-centre path renders identically app-wide (budget tree,
 * bookings, application-detail badge, dropdowns …).
 */
export function simplifyPathKey(pathKey: string): string {
  const seg = pathKey.split('-');
  const out: string[] = [];
  for (let i = 0; i < seg.length; i++) {
    const next = seg[i + 1];
    if (i > 0 && next && next.length > seg[i].length && next.startsWith(seg[i])) continue;
    out.push(seg[i]);
  }
  return out.join('-');
}

/** Pipe form of {@link simplifyPathKey} for templates: `{{ pathKey | simplifyPath }}`. */
@Pipe({ name: 'simplifyPath', standalone: true })
export class SimplifyPathPipe implements PipeTransform {
  transform(pathKey: string | null | undefined): string {
    return pathKey ? simplifyPathKey(pathKey) : '';
  }
}
