import { Pipe, type PipeTransform } from '@angular/core';

/**
 * Pfad-Schlüssel zur Anzeige vereinfachen: numerische Präfix-Ketten einklappen.
 * Ist ein Segment Präfix des nächsten (8→81→810), bleibt nur das längste übrig.
 * Das Top-Level-Segment bleibt immer erhalten. ``VSM-8-81-810-330 → VSM-810-330``.
 *
 * Geteilt (#path-display), damit jeder Kostenstellen-Pfad app-weit identisch
 * dargestellt wird (Budget-Baum, Buchungen, Antragsdetail-Badge, Dropdowns …).
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

/** Pipe-Form von {@link simplifyPathKey} für Templates: `{{ pathKey | simplifyPath }}`. */
@Pipe({ name: 'simplifyPath', standalone: true })
export class SimplifyPathPipe implements PipeTransform {
  transform(pathKey: string | null | undefined): string {
    return pathKey ? simplifyPathKey(pathKey) : '';
  }
}
