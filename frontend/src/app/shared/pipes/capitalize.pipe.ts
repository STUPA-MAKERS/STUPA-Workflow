import { Pipe, type PipeTransform } from '@angular/core';

/**
 * Anzeige-Kapitalisierung (#73): erster Buchstabe jedes Wortes groß, Rest
 * unverändert. Rein kosmetisch — der zugrundeliegende **Wert** (z. B. Rollen-Key
 * `member`) bleibt unangetastet, nur die Darstellung wird kapitalisiert. Trenner
 * sind Leerraum, `-` und `_`, damit `stupa_admin` → `Stupa_Admin` / `vote-manager`
 * → `Vote-Manager` lesbar werden.
 */
@Pipe({ name: 'capitalize', standalone: true, pure: true })
export class CapitalizePipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value) return '';
    return value.replace(/(^|[\s\-_])(\p{L})/gu, (_m, sep: string, ch: string) => sep + ch.toUpperCase());
  }
}
