import { Pipe, type PipeTransform } from '@angular/core';

/**
 * The one place a cost-centre path key is prepared for display.
 *
 * It returns the key UNCHANGED, deliberately. It used to collapse numeric prefix chains
 * — when a segment was a prefix of the next one, `VSM-8-81-810-330` became `VSM-810-330`
 * — and that proved too unstable to keep: whether a segment counted as a prefix depended
 * on how the committee happened to have numbered its cost centres, so the same path could
 * shorten differently after an unrelated rename. The committee is renaming its cost
 * centres instead, which fixes the underlying problem rather than papering over it.
 *
 * This is NOT dead code. It stays because every view already routes its path keys through
 * it, so a future attempt has one seam to change and does not have to find twelve call
 * sites again. Deleting it would cost more than keeping it.
 */
export function simplifyPathKey(pathKey: string): string {
  return pathKey;
}

/** Pipe form of {@link simplifyPathKey} for templates: `{{ pathKey | simplifyPath }}`. */
@Pipe({ name: 'simplifyPath', standalone: true })
export class SimplifyPathPipe implements PipeTransform {
  transform(pathKey: string | null | undefined): string {
    return pathKey ? simplifyPathKey(pathKey) : '';
  }
}
