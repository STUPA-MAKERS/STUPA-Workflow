import { Pipe, type PipeTransform } from '@angular/core';

/**
 * Display capitalization: uppercase the first letter of each word, rest unchanged.
 * Purely cosmetic — the underlying **value** (e.g. the role key `member`) stays
 * untouched, only the display is capitalized. Separators are whitespace, `-` and
 * `_`, so `stupa_admin` → `Stupa_Admin` / `vote-manager` → `Vote-Manager` read well.
 */
@Pipe({ name: 'capitalize', standalone: true, pure: true })
export class CapitalizePipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value) return '';
    return value.replace(/(^|[\s\-_])(\p{L})/gu, (_m, sep: string, ch: string) => sep + ch.toUpperCase());
  }
}
