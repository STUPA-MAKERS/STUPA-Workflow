import { Pipe, type PipeTransform } from '@angular/core';

/**
 * Capitalize a value for the display. The pipe makes the first letter of each word
 * uppercase and keeps the rest unchanged.
 *
 * The change is cosmetic. The stored value, for example the role key `member`, does not
 * change. The pipe splits words at whitespace, at `-` and at `_`. Therefore `stupa_admin`
 * reads as `Stupa_Admin` and `vote-manager` reads as `Vote-Manager`.
 */
@Pipe({ name: 'capitalize', standalone: true, pure: true })
export class CapitalizePipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value) return '';
    return value.replace(/(^|[\s\-_])(\p{L})/gu, (_m, sep: string, ch: string) => sep + ch.toUpperCase());
  }
}
