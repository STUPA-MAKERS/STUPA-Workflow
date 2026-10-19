import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import type { Subscription } from 'rxjs';
import {
  GremienApiService,
  type GremiumAttendance,
  type GremiumAttendanceRow,
} from '@core/api/gremien.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { downloadBlob } from '@shared/download.util';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { ButtonComponent, IconComponent, MEDIA, mediaQuery } from '@stupa-makers/ui-kit';
import { AttendanceDetailComponent } from '../attendance-detail/attendance-detail.component';
import { GREMIEN_NOW } from '../gremien.store';
import {
  type AttendanceSort,
  type CellView,
  type MonthRange,
  type RangePreset,
  type RowTotals,
  cellStrength,
  cellView,
  fileSlug,
  localized,
  monthAverages,
  oneDecimal,
  personName,
  presetRange,
  rangeLabel,
  rowTotals,
  semesterOf,
  sortRows,
  toCsv,
} from '../gremien.util';
import { monthShort, monthYear } from '@shared/date-format';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { NoteComponent } from '@shared/ui/note/note.component';

const PRESETS: readonly RangePreset[] = ['last6', 'last12', 'last24', 'semester', 'prevSemester'];
const SORTS: readonly AttendanceSort[] = ['quotaAsc', 'quotaDesc', 'name'];
const SORT_KEYS: Record<AttendanceSort, TranslationKey> = {
  quotaAsc: 'gremien.attendance.sortQuotaAsc',
  quotaDesc: 'gremien.attendance.sortQuotaDesc',
  name: 'gremien.attendance.sortName',
};

/** One head cell of a month. */
export interface MonthHead {
  readonly month: string;
  readonly short: string;
  readonly long: string;
  readonly meetings: string;
}

/** One cell, ready for the template. */
export interface CellModel {
  readonly view: CellView;
  readonly month: string;
  readonly label: string;
  /** The accent share of the background, in percent. */
  readonly strength: number;
}

/** One person, ready for the template. */
export interface RowModel {
  readonly row: GremiumAttendanceRow;
  readonly name: string;
  readonly role: string;
  readonly totals: RowTotals;
  readonly cells: readonly CellModel[];
}

/**
 * The sub-tab "Anwesenheit" of a gremium: one row per person, one column per month.
 *
 * - A head cell holds the month and the number of closed meetings. A cell shows
 *   "anwesend/Sitzungen", coloured by the share; a warning badge with a number counts
 *   the excused meetings and a grey badge "nV" the meetings with a transferred vote. A
 *   hatched cell is a month without a membership, "–" a month without a meeting.
 * - The last column sums the months with a membership, with the quota; the foot gives
 *   "Ø anwesend je Sitzung". The head row and the first column stick while the matrix
 *   scrolls in both directions.
 * - A click on a cell opens the meetings of that month (`AttendanceDetailComponent`).
 * - The chips "Zeitraum" (last 6, 12 or 24 months, this or the last semester), "Rolle"
 *   and "Sortierung" (quota ascending by default). "Als CSV exportieren" saves the
 *   matrix from the same answer, in the browser.
 * - A phone shows a card per person with a small cell per month; a tap opens the bottom
 *   sheet with every meeting of the range.
 * - A range without a meeting shows a grey skeleton of the matrix, not an error.
 */
@Component({
  selector: 'app-gremium-attendance',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.gat-host--fill]': 'fill()' },
  imports: [
    NoteComponent,
    EmptyStateComponent,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    AvatarComponent,
    FilterSelectComponent,
    SkeletonComponent,
    AttendanceDetailComponent,
  ],
  templateUrl: './gremium-attendance.component.html',
  styleUrl: './gremium-attendance.component.scss',
})
export class GremiumAttendanceComponent {
  private readonly api = inject(GremienApiService);
  private readonly i18n = inject(I18nService);
  private readonly now = inject(GREMIEN_NOW);

  readonly gremiumId = input.required<string>();
  readonly gremiumName = input('');
  /** The sheet is as high as the pane: the matrix takes the free height and scrolls. */
  readonly fill = input(false);

  readonly phone = mediaQuery(MEDIA.phone);
  private readonly detail = viewChild(AttendanceDetailComponent);

  readonly preset = signal<RangePreset>('last6');
  readonly role = signal('');
  readonly sort = signal<AttendanceSort>('quotaAsc');
  readonly loading = signal(true);
  readonly error = signal(false);
  readonly data = signal<GremiumAttendance | null>(null);
  private sub: Subscription | null = null;

  readonly range = computed<MonthRange>(() => presetRange(this.preset(), this.now()));

  readonly rangeOptions = computed<FilterSelectOption[]>(() =>
    PRESETS.map((p) => ({ value: p, label: this.presetLabel(p) })),
  );
  readonly rangeText = computed(() => {
    const r = this.range();
    return `${this.i18n.translate('gremien.attendance.range')}: ${rangeLabel(r.from, r.to, this.i18n.locale())}`;
  });

  readonly sortOptions = computed<FilterSelectOption[]>(() =>
    SORTS.map((s) => ({ value: s, label: this.i18n.translate(SORT_KEYS[s]) })),
  );
  readonly sortText = computed(
    () => `${this.i18n.translate('gremien.attendance.sort')}: ${this.i18n.translate(SORT_KEYS[this.sort()])}`,
  );

  readonly roleOptions = computed<FilterSelectOption[]>(() => {
    const locale = this.i18n.locale();
    const roles = new Map<string, string>();
    for (const r of this.data()?.rows ?? []) {
      if (r.roleKey && !roles.has(r.roleKey)) roles.set(r.roleKey, localized(r.roleName, locale, r.roleKey));
    }
    return [
      { value: '', label: this.i18n.translate('gremien.members.roleAll') },
      ...[...roles].map(([value, label]) => ({ value, label })),
    ];
  });
  readonly roleText = computed(() => {
    const role = this.role();
    if (!role) return null;
    const label = this.roleOptions().find((o) => o.value === role)?.label ?? role;
    return `${this.i18n.translate('gremien.members.role')}: ${label}`;
  });

  readonly months = computed(() => this.data()?.months ?? []);

  readonly heads = computed<MonthHead[]>(() => {
    const locale = this.i18n.formatLocale();
    return this.months().map((m) => ({
      month: m.month,
      short: monthShort(m.month, locale),
      long: monthYear(m.month, locale),
      meetings: this.meetingsText(m.meetings),
    }));
  });
  readonly totalMeetings = computed(() => this.months().reduce((n, m) => n + m.meetings, 0));
  readonly totalText = computed(() => this.meetingsText(this.totalMeetings()));
  /** No closed meeting in the range: the grey skeleton shows. */
  readonly noMeetings = computed(() => !!this.data() && this.totalMeetings() === 0);

  readonly rows = computed<RowModel[]>(() => {
    const data = this.data();
    if (!data) return [];
    const locale = this.i18n.locale();
    const role = this.role();
    const filtered = data.rows.filter((r) => !role || r.roleKey === role);
    // The phone cards go by name, as the board shows them.
    const sorted = sortRows(filtered, data.months, this.phone() ? 'name' : this.sort(), locale);
    return sorted.map((row) => {
      const name = personName(row.displayName);
      return {
        row,
        name,
        role: localized(row.roleName, locale, row.roleKey ?? ''),
        totals: rowTotals(row, data.months),
        cells: row.cells.map((cell, i) => {
          const view = cellView(cell, data.months[i]?.meetings ?? 0);
          return {
            view,
            month: cell.month,
            label: this.cellLabel(name, cell.month, view),
            strength: cellStrength(view.share),
          };
        }),
      };
    });
  });

  readonly averages = computed(() => {
    const locale = this.i18n.locale();
    const avg = monthAverages(this.rows().map((r) => r.row), this.months());
    const fmt = (v: number | null) => (v === null ? '—' : oneDecimal(v, locale));
    return { months: avg.months.map(fmt), total: fmt(avg.total) };
  });

  constructor() {
    effect(() => {
      const id = this.gremiumId();
      const range = this.range();
      untracked(() => this.load(id, range));
    });
  }

  load(id = this.gremiumId(), range = this.range()): void {
    this.sub?.unsubscribe();
    this.loading.set(true);
    this.error.set(false);
    this.sub = this.api.attendance(id, range).subscribe({
      next: (data) => {
        this.data.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.data.set(null);
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  setPreset(value: string): void {
    this.preset.set((PRESETS as readonly string[]).includes(value) ? (value as RangePreset) : 'last6');
  }

  setSort(value: string): void {
    this.sort.set((SORTS as readonly string[]).includes(value) ? (value as AttendanceSort) : 'quotaAsc');
  }

  /** "Gesamt" in the head: flip the quota order. */
  toggleQuotaSort(): void {
    this.sort.set(this.sort() === 'quotaAsc' ? 'quotaDesc' : 'quotaAsc');
  }

  /** A cell: the meetings of that month, in the popover. */
  openCell(model: RowModel, cell: CellModel, anchor: EventTarget | null): void {
    const v = cell.view;
    this.detail()?.open(
      {
        principalId: model.row.principalId,
        name: model.name,
        heading: `${model.name} · ${monthYear(cell.month, this.i18n.formatLocale())}`,
        summary: this.summary(v.present, v.held, v.excused, v.delegated),
        months: [cell.month],
      },
      anchor,
    );
  }

  /** A card (phone): every month of the range with a meeting, in the bottom sheet. */
  openPerson(model: RowModel, anchor: EventTarget | null): void {
    const r = this.range();
    const months = this.months()
      .filter((m, i) => m.meetings > 0 && (model.row.cells[i]?.member ?? false))
      .map((m) => m.month)
      .reverse();
    const parts = [
      model.role,
      this.i18n.translate('gremien.attendance.ofPresent', {
        present: model.totals.present,
        held: model.totals.held,
      }),
      rangeLabel(r.from, r.to, this.i18n.locale()),
    ].filter(Boolean);
    this.detail()?.open(
      {
        principalId: model.row.principalId,
        name: model.name,
        heading: model.name,
        summary: parts.join(' · '),
        months,
      },
      anchor,
    );
  }

  /** "Als CSV exportieren": the matrix as it shows, from the same answer. */
  exportCsv(): void {
    const data = this.data();
    if (!data) return;
    const t = (k: TranslationKey) => this.i18n.translate(k);
    const locale = this.i18n.formatLocale();
    const head = [t('gremien.attendance.member'), t('gremien.members.role')];
    for (const m of data.months) {
      const label = monthYear(m.month, locale);
      head.push(
        `${label} ${t('gremien.attendance.csvMeetings')}`,
        `${label} ${t('gremien.attendance.csvPresent')}`,
        `${label} ${t('gremien.attendance.csvExcused')}`,
        `${label} ${t('gremien.attendance.csvDelegated')}`,
      );
    }
    head.push(
      `${t('gremien.attendance.total')} ${t('gremien.attendance.csvPresent')}`,
      `${t('gremien.attendance.total')} ${t('gremien.attendance.csvMeetings')}`,
      `${t('gremien.attendance.total')} %`,
    );
    const body = this.rows().map((r) => {
      const line: (string | number | null)[] = [r.name, r.role];
      r.cells.forEach((c) => {
        if (c.view.kind === 'na') line.push(null, null, null, null);
        else line.push(c.view.held, c.view.present, c.view.excused, c.view.delegated);
      });
      line.push(r.totals.present, r.totals.held, r.totals.pct);
      return line;
    });
    const range = this.range();
    downloadBlob(
      new Blob([toCsv([head, ...body])], { type: 'text/csv;charset=utf-8' }),
      `${fileSlug(this.gremiumName())}-anwesenheit-${range.from}-${range.to}.csv`,
    );
  }

  private presetLabel(preset: RangePreset): string {
    const semester = preset === 'semester' || preset === 'prevSemester' ? semesterOf(presetRange(preset, this.now())) : null;
    if (semester) {
      return semester.summer
        ? this.i18n.translate('gremien.attendance.summer', { year: semester.year })
        : this.i18n.translate('gremien.attendance.winter', {
            years: `${String(semester.year).slice(2)}/${String(semester.year + 1).slice(2)}`,
          });
    }
    const key: Record<string, TranslationKey> = {
      last12: 'gremien.attendance.last12',
      last24: 'gremien.attendance.last24',
    };
    return this.i18n.translate(key[preset] ?? 'gremien.attendance.last6');
  }

  private meetingsText(n: number): string {
    return n === 1
      ? this.i18n.translate('gremien.attendance.meetings1')
      : this.i18n.translate('gremien.attendance.meetings', { n });
  }

  /** "1 von 2 Sitzungen anwesend, 1 entschuldigt, 1 Stimme übertragen". */
  private summary(present: number, held: number, excused: number, delegated: number): string {
    const parts = [this.i18n.translate('gremien.attendance.summary', { present, held })];
    if (excused) parts.push(this.i18n.translate('gremien.attendance.cellExcused', { n: excused }));
    if (delegated) parts.push(this.i18n.translate('gremien.attendance.cellDelegated', { n: delegated }));
    return parts.join(', ');
  }

  private cellLabel(name: string, month: string, view: CellView): string {
    const when = monthYear(month, this.i18n.formatLocale());
    if (view.kind === 'na') return this.i18n.translate('gremien.attendance.cellNa', { name, month: when });
    if (view.kind === 'none') return this.i18n.translate('gremien.attendance.cellNone', { name, month: when });
    return `${name}, ${when}: ${this.summary(view.present, view.held, view.excused, view.delegated)}`;
  }
}
