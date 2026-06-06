import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';

interface BarRow {
  option: string;
  label: string;
  count: number;
  /** Balkenbreite in Prozent (relativ zu eligible bzw. Maximum). */
  pct: number;
  leading: boolean;
}

/**
 * Präsentationskomponente: Ergebnis-Balken pro Option mit Stimmenzahl. Teilt
 * sich Vote-Cast, Live-Vote und Beamer (api.md §4). Zeigt **nie** Namen — nur
 * aggregierte Counts. Balkenbreite bezieht sich auf die Zahl der
 * Stimmberechtigten (`eligible`), damit der Fortschritt zum Quorum sichtbar ist;
 * fehlt `eligible`, wird relativ zum Maximum skaliert.
 */
@Component({
  selector: 'app-vote-bars',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './vote-bars.component.html',
  styleUrl: './vote-bars.component.scss',
})
export class VoteBarsComponent {
  private readonly i18n = inject(I18nService);

  readonly options = input.required<string[]>();
  readonly counts = input.required<Record<string, number>>();
  readonly eligible = input<number>(0);
  readonly leading = input<string | null>(null);
  readonly variant = input<'compact' | 'beamer'>('compact');

  readonly rows = computed<BarRow[]>(() => {
    const counts = this.counts();
    const max = Math.max(1, ...this.options().map((o) => counts[o] ?? 0));
    const base = this.eligible() > 0 ? this.eligible() : max;
    return this.options().map((option) => {
      const count = counts[option] ?? 0;
      return {
        option,
        label: this.optionLabel(option),
        count,
        pct: base > 0 ? Math.min(100, (count / base) * 100) : 0,
        leading: this.leading() === option,
      };
    });
  });

  /** Bekannte Optionen (`yes`/`no`/`abstain`) i18n-übersetzen, sonst Roh-Key. */
  private optionLabel(option: string): string {
    const key = `vote.option.${option}` as TranslationKey;
    const label = this.i18n.translate(key);
    return label === key ? option : label;
  }
}
