import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
} from '@angular/core';
import type { Uuid } from '@core/api/models';
import { PaperlessService, type PaperlessCopy, type PaperlessHit } from '@core/api/paperless.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { SearchWindowComponent, type SearchWindowRow, ToastService, liveSearch } from '@stupa-makers/ui-kit';

/** The i18n key of a failed copy, from the HTTP status of the problem response. */
export function paperlessInsertErrorKey(status?: number): TranslationKey {
  switch (status) {
    case 403:
      return 'paperless.insert.error.forbidden';
    case 413:
      return 'paperless.insert.error.tooLarge';
    case 415:
      return 'paperless.insert.error.type';
    case 503:
      return 'paperless.insert.error.unavailable';
    default:
      return 'paperless.insert.error.failed';
  }
}

/**
 * The Paperless search of a protocol text (§F/integrations/paperless/002534): the search
 * window of the kit over the documents of Paperless. Before the first typed character it
 * shows the documents that Paperless added last. A pick copies the document into the
 * protocol of the Sitzung (§002528) and emits the copy; the window then closes. An outage
 * shows as a line in the window, and the editor under it keeps its text (§002529).
 */
@Component({
  selector: 'app-paperless-insert',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SearchWindowComponent, TranslatePipe],
  templateUrl: './paperless-insert.component.html',
})
export class PaperlessInsertComponent {
  private readonly api = inject(PaperlessService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = model(false);
  readonly meetingId = input.required<Uuid>();
  /** The copy of the picked document: an embedded PDF of the Sitzung. */
  readonly inserted = output<PaperlessCopy>();

  protected readonly hits = signal<readonly PaperlessHit[]>([]);
  protected readonly failed = signal(false);
  /** The copy of a pick runs: a second pick waits. */
  protected readonly copying = signal(false);

  protected readonly search = liveSearch<PaperlessHit[]>({
    run: (q) => {
      this.failed.set(false);
      return this.api.search(q);
    },
    result: (hits) => this.hits.set(hits),
    error: () => {
      this.hits.set([]);
      this.failed.set(true);
    },
  });

  protected readonly rows = computed<SearchWindowRow[]>(() =>
    this.hits().map((hit) => ({
      id: String(hit.documentId),
      icon: 'file' as const,
      title: hit.title,
      subtitle: this.subtitle(hit),
    })),
  );

  /** An opening starts with an empty field and the documents that Paperless added last. */
  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        this.hits.set([]);
        this.search.sync('');
        this.search.refresh();
      });
    });
  }

  /** The field changed. The window empties its field on an opening: that is no new search. */
  protected onQuery(value: string): void {
    if (value !== this.search.text()) this.search.set(value);
  }

  /** The document type and the date of the document, in one line. */
  private subtitle(hit: PaperlessHit): string {
    const date = hit.created
      ? new Intl.DateTimeFormat(this.i18n.formatLocale(), { dateStyle: 'medium', timeZone: 'UTC' }).format(
          new Date(`${hit.created}T00:00:00Z`),
        )
      : null;
    return [hit.documentType, date].filter(Boolean).join(' · ');
  }

  protected pick(row: SearchWindowRow): void {
    if (this.copying()) return;
    this.copying.set(true);
    this.api.insert(this.meetingId(), Number(row.id)).subscribe({
      next: (copy) => {
        this.copying.set(false);
        this.open.set(false);
        this.inserted.emit(copy);
      },
      error: (err: { status?: number } | null) => {
        this.copying.set(false);
        this.toast.show(this.i18n.translate(paperlessInsertErrorKey(err?.status)), 'error');
      },
    });
  }
}
