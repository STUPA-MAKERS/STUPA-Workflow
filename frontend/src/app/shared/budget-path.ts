import { Pipe, type PipeTransform } from '@angular/core';

/**
 * The one place a cost-centre path key is prepared for display.
 *
 * It returns the key UNCHANGED. Shortening a path by collapsing numeric prefix chains
 * depends on how a committee numbers its cost centres, so the same path shortens
 * differently after an unrelated rename; the committee renames its cost centres instead.
 *
 * This is NOT dead code. Every view routes its path keys through it, so a change to how
 * a path reads has one seam rather than twelve call sites.
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
