import { NgTemplateOutlet } from '@angular/common';
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
import { Subject, debounceTime, switchMap } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiClient } from '@core/api/api-client.service';
import type { SearchHit, SearchKind } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';
import { PageIndexService, type PageEntry } from './page-index.service';

/** One row of the palette. A page comes from the client, a record from the server. */
interface PaletteRow {
  key: string;
  group: string;
  title: string;
  subtitle: string | null;
  icon: IconName;
  url: string;
}

/** How long to wait after a keystroke before asking the server. */
const DEBOUNCE_MS = 180;

/** The server ignores anything shorter, so the client does not ask. */
const MIN_QUERY = 2;

/** Picked from the icons the kit actually has, not from what each kind would ideally
    want. A wrong-but-present glyph beats a name that fails to compile. */
const KIND_ICON: Record<SearchKind, IconName> = {
  application: 'document',
  meeting: 'clock',
  invoice: 'euro',
  expense: 'chart-pie',
  budget: 'chart-pie',
  gremium: 'parliament',
  principal: 'user',
};

/**
 * Global search, as a command palette.
 *
 * It answers two different questions with one box, because a reader does not separate
 * them: "take me to that application" and "take me to the settings page for roles".
 * Pages come from the route table and are filtered by the same permissions the router
 * guard applies, so they appear instantly and never offer somewhere the user cannot go.
 * Records come from `GET /api/search`, which reuses each module's own read gate.
 *
 * The dialog is deliberately not `app-dialog`: that component centres a card in the
 * viewport and traps focus around a title and a footer. A palette sits high, owns the
 * keyboard, and has neither.
 */
@Component({
  selector: 'app-command-palette',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, NgTemplateOutlet, TranslatePipe, IconComponent],
  templateUrl: './command-palette.component.html',
  styleUrl: './command-palette.component.scss',
})
export class CommandPaletteComponent {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  private readonly i18n = inject(I18nService);
  private readonly pages = inject(PageIndexService);

  private readonly field = viewChild<ElementRef<HTMLInputElement>>('field');

  readonly open = signal(false);
  readonly query = signal('');
  readonly loading = signal(false);
  /** Index of the highlighted row, over the flattened list. */
  readonly active = signal(0);

  private readonly hits = signal<SearchHit[]>([]);
  private readonly truncated = signal(false);
  private readonly typed = new Subject<string>();

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
        icon: 'gear' as IconName,
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

  readonly showEmpty = computed(
    () => !this.loading() && this.query().trim().length >= MIN_QUERY && !this.rows().length,
  );
  readonly showTruncated = computed(() => this.truncated() && this.rows().length > 0);

  constructor() {
    this.typed
      .pipe(
        debounceTime(DEBOUNCE_MS),
        // `switchMap` cancels the in-flight request: with a slow connection the answer
        // to "ab" must never overwrite the answer to "abcd".
        switchMap((q) => this.api.search(q)),
        takeUntilDestroyed(),
      )
      .subscribe({
        next: (res) => {
          this.hits.set(res.hits);
          this.truncated.set(res.truncated);
          this.loading.set(false);
          this.active.set(0);
        },
        error: () => {
          this.hits.set([]);
          this.loading.set(false);
        },
      });

    // Focus the field once the overlay is in the DOM.
    effect(() => {
      if (this.open()) queueMicrotask(() => this.field()?.nativeElement.focus());
    });
  }

  show(): void {
    this.query.set('');
    this.hits.set([]);
    this.truncated.set(false);
    this.active.set(0);
    this.open.set(true);
  }

  close(): void {
    this.open.set(false);
    this.loading.set(false);
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
      this.active.set((this.active() + 1) % rows.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.active.set((this.active() - 1 + rows.length) % rows.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const row = rows[this.active()];
      if (row) this.go(row);
    }
  }

  go(row: PaletteRow): void {
    this.close();
    // The url can carry a query string (`/budget?ks=…`), which `navigateByUrl` parses
    // and `navigate` would not.
    void this.router.navigateByUrl(row.url);
  }

  /** Flat index of a row, so the template can mark the active one across groups. */
  indexOf(row: PaletteRow): number {
    return this.rows().findIndex((r) => r.key === row.key);
  }

  protected readonly rowKey = (_i: number, row: PaletteRow): string => row.key;
}
