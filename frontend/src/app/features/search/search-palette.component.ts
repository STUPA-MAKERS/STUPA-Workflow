import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiClient } from '@core/api/api-client.service';
import type { SearchHit, SearchKind, SearchResults } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { type IconName, liveSearch } from '@stupa-makers/ui-kit';
import {
  CommandPalette,
  CommandPaletteComponent,
  type PaletteGroup,
  type PaletteRow,
} from '@stupa-makers/ui-kit/shell';
import { PageIndexService, type PageEntry } from './page-index.service';

/** How long to wait after a keystroke before asking the server. */
const DEBOUNCE_MS = 180;

/** The server ignores anything shorter, so the client does not ask. */
const MIN_QUERY = 2;

/** The icons of the records: the same icons the navigation uses for their areas. */
const KIND_ICON: Record<SearchKind, IconName> = {
  application: 'file',
  meeting: 'users',
  invoice: 'receipt',
  expense: 'swap',
  budget: 'pie',
  gremium: 'landmark',
  principal: 'user',
  ticket: 'ticket',
  todo: 'circleok',
};

/**
 * The icon for a page row, keyed on the leading path segment: the icon of the area in
 * the navigation. Admin pages keep the gear, because there it is true.
 */
const SECTION_ICON: Record<string, IconName> = {
  dashboard: 'home',
  applications: 'file',
  apply: 'fileplus',
  tasks: 'tasks',
  meetings: 'users',
  voting: 'vote',
  budget: 'pie',
  expenses: 'swap',
  invoices: 'receipt',
  account: 'user',
  admin: 'gear',
};

/** The leading segment of a route path, which is the section it belongs to. */
function sectionIcon(path: string): IconName {
  return SECTION_ICON[path.replace(/^\//, '').split('/')[0]] ?? 'gear';
}

/** A row of the palette with the label of its group. */
interface SourceRow extends PaletteRow {
  readonly group: string;
}

const EMPTY: SearchResults = { hits: [], truncated: false, failed: [] };

/**
 * The sources of the global search, shown in the search palette of the kit
 * (`app-command-palette`).
 *
 * It answers two different questions with one box, because a reader does not separate
 * them: "take me to that application" and "take me to the settings page for roles".
 * Pages come from the route table and are filtered by the same permissions the router
 * guard applies, so they appear instantly and never offer somewhere the user cannot go.
 * Records come from `GET /api/search`, which reuses each module's own read gate.
 *
 * The palette owns the dialog and the keyboard; the {@link CommandPalette} service opens it
 * from anywhere, and Ctrl+K (⌘K) toggles it.
 */
@Component({
  selector: 'app-search-palette',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommandPaletteComponent],
  template: `
    <app-command-palette
      [groups]="groups()"
      [query]="query()"
      [loading]="loading()"
      [truncated]="truncated()"
      [minQuery]="minQuery"
      (queryChange)="onQuery($event)"
    />
  `,
})
export class SearchPaletteComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly pages = inject(PageIndexService);

  protected readonly minQuery = MIN_QUERY;

  readonly query = signal('');
  /**
   * The record search: debounce, a new query cancels the request that is still out, and
   * a query below the floor clears the previous answer at once.
   */
  private readonly search = liveSearch<SearchResults>({
    minLength: MIN_QUERY,
    debounceMs: DEBOUNCE_MS,
    run: (q) => this.api.search(q),
    result: (res) => this.showResults(res),
    reset: () => this.showResults(EMPTY),
    error: () => this.showResults(EMPTY),
  });
  readonly loading = this.search.pending;

  private readonly hits = signal<SearchHit[]>([]);
  readonly truncated = signal(false);

  /** Pages that match, filtered to what this user may actually open. */
  private readonly pageRows = computed<SourceRow[]>(() => {
    const q = this.query().trim().toLowerCase();
    if (!q) return [];
    return this.pages
      .visible()
      .filter((p: PageEntry) => p.label.toLowerCase().includes(q))
      .slice(0, 5)
      .map((p) => ({
        id: `page:${p.path}`,
        group: this.i18n.translate('search.group.pages'),
        title: p.label,
        subtitle: p.parentLabel,
        icon: sectionIcon(p.path),
        link: p.path,
      }));
  });

  private readonly recordRows = computed<SourceRow[]>(() =>
    this.hits().map((h) => ({
      id: `${h.kind}:${h.id}`,
      group: this.i18n.translate(`search.group.${h.kind}`),
      title: h.title,
      subtitle: h.subtitle,
      icon: KIND_ICON[h.kind],
      link: h.url,
      status: h.kind === 'application',
      archived: h.archived,
    })),
  );

  /** Pages first: they are instant and exact, and a record needs a round trip. */
  readonly groups = computed<PaletteGroup[]>(() => {
    const out: { label: string; rows: SourceRow[] }[] = [];
    for (const row of [...this.pageRows(), ...this.recordRows()]) {
      const last = out[out.length - 1];
      if (last && last.label === row.group) last.rows.push(row);
      else out.push({ label: row.group, rows: [row] });
    }
    return out;
  });

  /** Each opening starts with an empty field and no answer of the last search. */
  constructor() {
    inject(CommandPalette)
      .opened$.pipe(takeUntilDestroyed())
      .subscribe(() => {
        this.query.set('');
        this.search.sync('');
        this.showResults(EMPTY);
      });
  }

  onQuery(value: string): void {
    this.query.set(value);
    this.search.set(value);
  }

  /** Put an answer of the record search on screen. */
  private showResults(res: SearchResults): void {
    this.hits.set(res.hits);
    this.truncated.set(res.truncated);
  }
}
