import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ConfirmDialogComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  filterChipText,
  IconComponent,
  type ListRow,
  type LoadState,
  RowMenuComponent,
  type RowMenuSection,
  SearchPillComponent,
  ToastService,
  ButtonGroupComponent,
} from '@stupa-makers/ui-kit';
import {
  RecordsScreenComponent,
  ScreenFiltersDirective,
  ScreenRecordDirective,
  ScreenSearchDirective,
} from '@stupa-makers/ui-kit/screens';
import { localToday } from '@shared/date-format';
import { hitCount, listSearch, searchedRows } from '../list-search';

/** The period chip: the delegations of the meetings from today on, or of the past ones. */
type Period = 'active' | 'past';

/**
 * The admin overview of the delegations (`/admin/delegations`), a list page of Verwaltung
 * (§002690) with the search of Benutzer (§002691).
 *
 * The chip "Zeitraum" shows the delegations of the meetings from today on (or without a
 * date), newest meeting last, or those of the past meetings, newest first. Each row has
 * meeting, date, from → to, the tags "Stimmrecht" and "Pool", and "Widerrufen" in the ⋮
 * menu (danger, with a confirmation). An admin may revoke at any time. A member creates
 * the own delegation on the meeting page; the gremium must allow it.
 *
 * The substitute pool of a gremium has its own page below the Gremien (§002692).
 */
@Component({
  selector: 'app-delegations',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonGroupComponent,
    ConfirmDialogComponent,
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    IconComponent,
    FilterSelectComponent,
    RecordsScreenComponent,
    ScreenFiltersDirective,
    ScreenRecordDirective,
    ScreenSearchDirective,
    SearchPillComponent,
    RowMenuComponent,
  ],
  templateUrl: './delegations.component.html',
  styleUrl: './delegations.component.scss',
})
export class DelegationsComponent {
  private readonly api = inject(DelegationsApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly delegations = signal<Delegation[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly busy = signal(false);
  protected readonly confirmRevoke = signal<Delegation | null>(null);
  protected readonly period = signal<Period>('active');

  private readonly today = localToday();

  /** A delegation of a meeting from today on, or of a meeting without a date. */
  private isActive(d: Delegation): boolean {
    return !d.meetingDate || d.meetingDate >= this.today;
  }

  /** By meeting date, then by meeting title. */
  private sort(list: Delegation[], dir: 1 | -1): Delegation[] {
    return [...list].sort(
      (a, b) =>
        dir * (a.meetingDate ?? '9999').localeCompare(b.meetingDate ?? '9999') ||
        (a.meetingTitle ?? '').localeCompare(b.meetingTitle ?? ''),
    );
  }

  /** The ⋮ menu of a delegation row: revoke is its only action. */
  protected readonly rowMenu = computed<readonly RowMenuSection[]>(() => [
    { items: [{ id: 'revoke', label: this.i18n.translate('admin.deleg.revoke'), icon: 'x', danger: true }] },
  ]);

  protected readonly active = computed(() =>
    this.sort(
      this.delegations().filter((d) => this.isActive(d)),
      1,
    ),
  );
  protected readonly past = computed(() =>
    this.sort(
      this.delegations().filter((d) => !this.isActive(d)),
      -1,
    ),
  );

  /** The options of the chip "Zeitraum". */
  protected readonly periodOptions = computed<FilterSelectOption[]>(() => [
    { value: 'active', label: this.i18n.translate('admin.deleg.active') },
    { value: 'past', label: this.i18n.translate('admin.deleg.past') },
  ]);
  /** The text of the chip: "Zeitraum: Aktive Vertretungen". */
  protected readonly periodText = computed(() =>
    filterChipText(
      this.i18n.translate('admin.deleg.filter.period'),
      this.periodOptions().find((o) => o.value === this.period())?.label,
    ),
  );

  /** The search of the list (§002690, §002691). */
  protected readonly search = listSearch();
  /** The rows of the records screen (§ui-kit:002257). */
  protected readonly rows = computed<LoadState<readonly ListRow[]>>(() => {
    if (this.loading()) return { state: 'loading' };
    if (this.loadError())
      return {
        state: 'error',
        message: this.i18n.translate('admin.deleg.error'),
        retry: () => this.reload(),
      };
    const list = this.period() === 'past' ? this.past() : this.active();
    const rows = this.search
      .filter(list, (d) => [d.meetingTitle, this.who(d, 'from'), this.who(d, 'to')])
      .map((d) => ({ id: d.id, title: d.meetingTitle ?? '' }));
    return searchedRows(
      rows.length
        ? { state: 'ready', data: rows }
        : {
            state: 'empty',
            icon: 'handshake',
            heading: this.i18n.translate(
              this.period() === 'past' ? 'admin.deleg.nonePast' : 'admin.deleg.none',
            ),
          },
      this.search,
      this.i18n.translate('admin.list.noHits'),
    );
  });
  /** The hits of the search for the pill. */
  protected readonly hits = computed(() => hitCount(this.rows(), this.search));

  constructor() {
    this.reload();
  }

  /** The delegation of a row of the records screen. */
  protected delegationOf(id: string): Delegation {
    return this.delegations().find((d) => d.id === id)!;
  }

  protected setPeriod(value: string): void {
    this.period.set(value === 'past' ? 'past' : 'active');
  }

  protected who(d: Delegation, side: 'from' | 'to'): string {
    const name = side === 'from' ? d.delegatorName : d.delegateName;
    return name || this.i18n.translate('admin.gremien.unknownMember');
  }

  protected askRevoke(d: Delegation): void {
    this.confirmRevoke.set(d);
  }

  protected revoke(): void {
    const d = this.confirmRevoke();
    if (!d || this.busy()) return;
    this.busy.set(true);
    this.api.revoke(d.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.confirmRevoke.set(null);
        this.delegations.update((list) => list.filter((x) => x.id !== d.id));
        this.toast.show(this.i18n.translate('admin.deleg.revoked'), 'success');
      },
      error: () => {
        this.busy.set(false);
        this.toast.show(this.i18n.translate('admin.deleg.revokeFailed'), 'error');
      },
    });
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.list().subscribe({
      next: (list) => {
        this.delegations.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }
}
