import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { map } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicationListItem, Uuid } from '@core/api/models';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AutocompleteComponent, IconComponent, liveSearch } from '@stupa-makers/ui-kit';

/** The hits of one search: the newest matches of the type, archived ones included. */
export const PREDECESSOR_HITS = 20;

/**
 * "Vorgänger": search an earlier Antrag of the same type to link as the Vorgänger of a
 * Folgeantrag. The server lists only what the person may open (the Anträge list with
 * its read scope); archived Anträge count too, because last year's Antrag is often
 * archived. `excludeId` keeps the Antrag itself out of the hits.
 *
 * `picked` is the title of the chosen Vorgänger, or null; the field then shows it with
 * an × that emits `cleared`.
 */
@Component({
  selector: 'app-predecessor-field',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [AutocompleteComponent, IconComponent, LocalizedDatePipe, TranslatePipe],
  templateUrl: './predecessor-field.component.html',
  styleUrl: './predecessor-field.component.scss',
})
export class PredecessorFieldComponent {
  private readonly api = inject(ApiClient);

  readonly typeId = input.required<Uuid>();
  readonly excludeId = input<Uuid | null>(null);
  readonly picked = input<string | null>(null);
  readonly inputId = input('predecessor');

  readonly choose = output<ApplicationListItem>();
  readonly cleared = output<void>();

  readonly query = signal('');
  readonly hits = signal<readonly ApplicationListItem[]>([]);

  readonly search = liveSearch<readonly ApplicationListItem[]>({
    run: (q) =>
      this.api
        .listApplications({ type: this.typeId(), q, archived: 'all', limit: PREDECESSOR_HITS })
        .pipe(map((page) => page.items.filter((item) => item.id !== this.excludeId()))),
    result: (items) => this.hits.set(items),
    reset: () => this.hits.set([]),
    error: () => this.hits.set([]),
  });

  protected readonly open = computed(() => this.picked() === null && this.hits().length > 0);

  /** A new type starts a new search: the hits of another type do not fit. */
  constructor() {
    effect(() => {
      this.typeId();
      untracked(() => this.clearSearch());
    });
  }

  onQuery(text: string): void {
    this.query.set(text);
    this.search.set(text);
  }

  pick(item: ApplicationListItem): void {
    this.hits.set([]);
    this.query.set('');
    this.search.sync('');
    this.choose.emit(item);
  }

  clear(): void {
    this.clearSearch();
    this.cleared.emit();
  }

  private clearSearch(): void {
    this.hits.set([]);
    this.query.set('');
    this.search.sync('');
  }
}
