import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Subject, catchError, debounceTime, of, switchMap } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiClient } from '@core/api/api-client.service';
import type { SearchHit, SearchKind, SearchResults } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { StatusTextComponent } from '@shared/ui';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';
import { CommandPaletteService } from './command-palette.service';
import { highlight, type TextPart } from './highlight';
import { PageIndexService, type PageEntry } from './page-index.service';
import { isApplePlatform } from './shortcut';

/** One row of the palette. A page comes from the client, a record from the server. */
interface PaletteRow {
  key: string;
  group: string;
  title: string;
  subtitle: string | null;
  icon: IconName;
  url: string;
  /** The subtitle is the state of an application: it shows as status text. */
  status?: boolean;
  /** Applications only. The row marks it, so an archived hit is not read as current. */
  archived?: boolean;
}

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
  gremium: 'parliament',
  principal: 'user',
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

const EMPTY: SearchResults = { hits: [], truncated: false, failed: [] };

/**
 * Global search, as a command palette.
 *
 * It answers two different questions with one box, because a reader does not separate
 * them: "take me to that application" and "take me to the settings page for roles".
 * Pages come from the route table and are filtered by the same permissions the router
 * guard applies, so they appear instantly and never offer somewhere the user cannot go.
 * Records come from `GET /api/search`, which reuses each module's own read gate.
 *
 * The field is a combobox: the focus stays in it, the arrow keys move the active row
 * (`aria-activedescendant`), Enter opens it and Escape closes the palette. The
 * {@link CommandPaletteService} opens it from anywhere; Ctrl+K (⌘K) toggles it.
 */
@Component({
  selector: 'app-command-palette',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, IconComponent, StatusTextComponent],
  templateUrl: './command-palette.component.html',
  styleUrl: './command-palette.component.scss',
})
export class CommandPaletteComponent {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  private readonly i18n = inject(I18nService);
  private readonly pages = inject(PageIndexService);
  private readonly palette = inject(CommandPaletteService);

  private readonly field = viewChild<ElementRef<HTMLInputElement>>('field');

  /** `⎋` is the key's own symbol on Apple keyboards; elsewhere the word is clearer. */
  protected readonly escLabel = isApplePlatform() ? '⎋' : 'Esc';

  readonly open = this.palette.isOpen;
  readonly query = signal('');
  readonly loading = signal(false);
  /** Index of the highlighted row, over the flattened list. */
  readonly active = signal(0);

  private readonly hits = signal<SearchHit[]>([]);
  private readonly truncated = signal(false);
  private readonly typed = new Subject<string>();
  /** Where the focus was before the palette opened; it goes back there on close. */
  private returnFocus: HTMLElement | null = null;

  /** Pages that match, filtered to what this user may actually open. */
  private readonly pageRows = computed<PaletteRow[]>(() => {
    const q = this.query().trim().toLowerCase();
    if (!q) return [];
    return this.pages
      .visible()
      .filter((p: PageEntry) => p.label.toLowerCase().includes(q))
      .slice(0, 5)
      .map((p) => ({
        key: `page:${p.path}`,
        group: this.i18n.translate('search.group.pages'),
        title: p.label,
        subtitle: p.parentLabel,
        icon: sectionIcon(p.path),
        url: p.path,
      }));
  });

  private readonly recordRows = computed<PaletteRow[]>(() =>
    this.hits().map((h) => ({
      key: `${h.kind}:${h.id}`,
      group: this.i18n.translate(`search.group.${h.kind}`),
      title: h.title,
      subtitle: h.subtitle,
      icon: KIND_ICON[h.kind],
      url: h.url,
      // The server sends the state label as the subtitle of an application.
      status: h.kind === 'application',
      archived: h.archived,
    })),
  );

  /** Pages first: they are instant and exact, and a record needs a round trip. */
  readonly rows = computed<PaletteRow[]>(() => [...this.pageRows(), ...this.recordRows()]);

  /** The rows regrouped for rendering, keeping the flat order for the keyboard. */
  readonly groups = computed<{ label: string; rows: PaletteRow[] }[]>(() => {
    const out: { label: string; rows: PaletteRow[] }[] = [];
    for (const row of this.rows()) {
      const last = out[out.length - 1];
      if (last && last.label === row.group) last.rows.push(row);
      else out.push({ label: row.group, rows: [row] });
    }
    return out;
  });

  /** The id of the active row, for `aria-activedescendant`. */
  readonly activeId = computed(() => {
    const row = this.rows()[this.active()];
    return row ? this.optionId(row) : null;
  });

  readonly showEmpty = computed(
    () => !this.loading() && this.query().trim().length >= MIN_QUERY && !this.rows().length,
  );
  readonly showTruncated = computed(() => this.truncated() && this.rows().length > 0);

  constructor() {
    this.typed
      .pipe(
        debounceTime(DEBOUNCE_MS),
        // `switchMap` cancels the in-flight request: with a slow connection the answer
        // to "ab" must never overwrite the answer to "abcd". The error is caught INSIDE,
        // so one failed request does not end the search for the rest of the session.
        switchMap((q) =>
          this.api.search(q).pipe(
            catchError(() => {
              this.loading.set(false);
              return of(EMPTY);
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((res) => {
        this.hits.set(res.hits);
        this.truncated.set(res.truncated);
        this.loading.set(false);
        this.active.set(0);
      });

    // Every opening starts from a clean field, whoever opened it.
    this.palette.opened$.pipe(takeUntilDestroyed()).subscribe(() => this.reset());

    // Focus the field once the overlay is in the DOM.
    effect(() => {
      if (this.open()) queueMicrotask(() => this.field()?.nativeElement.focus());
    });
  }

  show(): void {
    this.palette.open();
  }

  close(): void {
    if (!this.open()) return;
    this.palette.close();
    this.loading.set(false);
    const target = this.returnFocus;
    this.returnFocus = null;
    if (target?.isConnected) target.focus();
  }

  onQuery(value: string): void {
    this.query.set(value);
    this.active.set(0);
    const q = value.trim();
    if (q.length < MIN_QUERY) {
      // Clear the previous answer straight away. Leaving it up while the user deletes
      // characters shows results for a query they can no longer see.
      this.hits.set([]);
      this.truncated.set(false);
      this.loading.set(false);
      return;
    }
    this.loading.set(true);
    this.typed.next(q);
  }

  @HostListener('document:keydown', ['$event'])
  onDocumentKey(event: KeyboardEvent): void {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (this.open()) this.close();
      else this.show();
      return;
    }
    if (!this.open()) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      this.close();
      return;
    }
    const rows = this.rows();
    if (!rows.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.moveTo(rows, (this.active() + 1) % rows.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.moveTo(rows, (this.active() - 1 + rows.length) % rows.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      // The rows can shrink under a kept index; the last row is then the nearest.
      this.go(rows[Math.min(this.active(), rows.length - 1)]);
    }
  }

  go(row: PaletteRow): void {
    // No focus return: the reader goes somewhere else.
    this.returnFocus = null;
    this.close();
    // The url can carry a query string (`/budget?ks=…`), which `navigateByUrl` parses
    // and `navigate` would not.
    void this.router.navigateByUrl(row.url);
  }

  /** Flat index of a row, so the template can mark the active one across groups. */
  indexOf(row: PaletteRow): number {
    return this.rows().findIndex((r) => r.key === row.key);
  }

  /** The parts of a text that match the query, for the highlight. */
  parts(text: string): TextPart[] {
    return highlight(text, this.query());
  }

  /** A stable DOM id for a row. */
  optionId(row: PaletteRow): string {
    return `palette-option-${row.key.replace(/[^A-Za-z0-9_-]/g, '-')}`;
  }

  private reset(): void {
    this.returnFocus = document.activeElement as HTMLElement | null;
    this.query.set('');
    this.hits.set([]);
    this.truncated.set(false);
    this.loading.set(false);
    this.active.set(0);
  }

  /** Make a row the active one and scroll it into the visible part of the list. */
  private moveTo(rows: PaletteRow[], index: number): void {
    this.active.set(index);
    const id = this.optionId(rows[index]);
    // After the render that moves the highlight.
    queueMicrotask(() => document.getElementById(id)?.scrollIntoView({ block: 'nearest' }));
  }
}
