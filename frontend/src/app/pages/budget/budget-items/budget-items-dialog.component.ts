import { ChangeDetectionStrategy, Component, computed, effect, inject, input, model, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, map, switchMap } from 'rxjs/operators';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { LoadMoreComponent } from '@shared/ui/load-more/load-more.component';
import {
  DialogComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  SearchPillComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';
import { type BudgetApplication, BudgetTreeApi, type Expense, type ExpensePage } from '../budget-tree.api';
import { BudgetItemListComponent } from './budget-item-list.component';
import { type BudgetItemType, mergeBudgetItems } from './budget-items';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';

/** Bookings per page. A search loads the largest page, because the server ranks its hits by
 *  relevance and not by date, so only one page keeps the merged list in date order. */
const PAGE = 50;
const SEARCH_PAGE = 200;

/** One request for a page of bookings. */
interface PageRequest {
  readonly ks: string;
  readonly fy: string;
  readonly q: string;
  readonly offset: number;
}

/**
 * All applications and bookings of a cost centre, in a dialog (a bottom sheet on a phone).
 *
 * A search field and a type chip filter the list. The applications come in full from the
 * page that opens the dialog and are filtered here. The bookings load page by page while
 * the reader scrolls (`app-load-more`), with the search on the server. See
 * `mergeBudgetItems` for the order.
 */
@Component({
  selector: 'app-budget-items-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    BudgetItemListComponent,
    DialogComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    LoadMoreComponent,
    LoadErrorComponent,
    SearchPillComponent,
    SkeletonComponent,
    TranslatePipe,
  ],
  templateUrl: './budget-items-dialog.component.html',
  styleUrl: './budget-items-dialog.component.scss',
})
export class BudgetItemsDialogComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);

  readonly open = model(false);
  readonly title = input.required<string>();
  /** The cost centre; its subtree counts too. */
  readonly ksId = input.required<string>();
  /** The fiscal year, or `''` for every year. */
  readonly fyId = input('');
  /** All applications of the cost centre, as the page loaded them. */
  readonly apps = input<readonly BudgetApplication[]>([]);
  /** The reader may read the bookings. Without it the list holds only applications. */
  readonly withBookings = input(false);
  readonly names = input<ReadonlyMap<string, { name: string }>>(new Map());

  readonly type = signal<BudgetItemType>('');
  /** The text in the search field, and the text the list is filtered by (debounced). */
  readonly query = signal('');
  readonly applied = signal('');

  readonly bookings = signal<readonly Expense[]>([]);
  readonly total = signal(0);
  /** A page of bookings is on its way; `first` is true for the first page. */
  readonly loading = signal(false);
  readonly loadingFirst = signal(false);
  readonly error = signal(false);

  private readonly typed = new Subject<string>();
  private readonly pages = new Subject<PageRequest>();

  /** The bookings take part: the reader may read them and the type chip allows them. */
  private readonly bookingsOn = computed(() => this.withBookings() && this.type() !== 'application');

  readonly bookingsDone = computed(() => !this.bookingsOn() || this.bookings().length >= this.total());

  readonly items = computed(() => {
    const q = this.applied().trim().toLowerCase();
    const apps =
      this.type() === 'booking'
        ? []
        : this.apps().filter((a) => !q || (a.title ?? '').toLowerCase().includes(q));
    return mergeBudgetItems(apps, this.bookingsOn() ? this.bookings() : [], this.bookingsDone());
  });

  readonly hasMore = computed(() => !this.bookingsDone() && !this.error());

  readonly typeOptions = computed<FilterSelectOption[]>(() =>
    (
      [
        ['', 'budget.dash.typeAll'],
        ['application', 'budget.dash.typeApplications'],
        ['booking', 'budget.dash.typeBookings'],
      ] as const satisfies readonly (readonly [BudgetItemType, TranslationKey])[]
    ).map(([value, key]) => ({ value, label: this.i18n.translate(key) })),
  );
  readonly typeText = computed(() => {
    const label = this.typeOptions().find((o) => o.value === this.type())?.label ?? '';
    return this.type() ? `${this.i18n.translate('budget.dash.type')}: ${label}` : null;
  });

  constructor() {
    this.typed.pipe(debounceTime(250), takeUntilDestroyed()).subscribe((q) => this.applied.set(q));
    this.pages
      .pipe(
        switchMap((r) =>
          this.api
            .listExpenses({
              budget: r.ks as Uuid,
              fiscalYear: (r.fy || undefined) as Uuid | undefined,
              q: r.q || undefined,
              sort: 'createdAt',
              order: 'desc',
              limit: r.q ? SEARCH_PAGE : PAGE,
              offset: r.offset,
            })
            .pipe(
              map((page): { r: PageRequest; page: ExpensePage | null } => ({ r, page })),
              catchError(() => of({ r, page: null })),
            ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe(({ r, page }) => {
        this.loading.set(false);
        this.loadingFirst.set(false);
        if (!page) {
          this.error.set(true);
          return;
        }
        this.bookings.set(r.offset === 0 ? page.items : [...this.bookings(), ...page.items]);
        this.total.set(page.total);
      });

    effect(() => {
      const open = this.open();
      const on = this.bookingsOn();
      const ks = this.ksId();
      const fy = this.fyId();
      const q = this.applied().trim();
      if (!open || !on || !ks) return;
      untracked(() => this.request({ ks, fy, q, offset: 0 }));
    });
  }

  onQuery(text: string): void {
    this.query.set(text);
    this.typed.next(text);
  }

  setType(value: string): void {
    this.type.set(value as BudgetItemType);
  }

  loadMore(): void {
    if (this.loading() || this.bookingsDone()) return;
    this.request({ ks: this.ksId(), fy: this.fyId(), q: this.applied().trim(), offset: this.bookings().length });
  }

  retry(): void {
    this.request({ ks: this.ksId(), fy: this.fyId(), q: this.applied().trim(), offset: this.bookings().length });
  }

  private request(r: PageRequest): void {
    this.error.set(false);
    this.loading.set(true);
    if (r.offset === 0) {
      this.loadingFirst.set(true);
      this.bookings.set([]);
      this.total.set(0);
    }
    this.pages.next(r);
  }

  close(): void {
    this.open.set(false);
  }
}
