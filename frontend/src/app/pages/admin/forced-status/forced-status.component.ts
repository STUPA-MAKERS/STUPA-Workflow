import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { FORCE_REASONS, type ForcedEvent, type ForcedReport } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { isoDay, localToday } from '@shared/date-format';
import { i18nLabel } from '@shared/forms/i18n-text';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DatepickerComponent,
  DialogComponent,
  EmptyStateComponent,
  PageHeaderComponent,
  SectionComponent,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';

/** The default period: the last 90 days (spec 001651, as the server). */
export const DEFAULT_DAYS = 90;

/** One row of a count table, with the filter of its list. */
export interface CountRow {
  readonly key: string;
  readonly label: string;
  readonly count: number;
  readonly filter: { readonly reason?: string; readonly fromKey?: string; readonly toKey?: string };
}

/** The first day of the default period: `DEFAULT_DAYS` before `today`. */
export function defaultFrom(today: string): string {
  const [y, m, d] = today.split('-').map(Number);
  return isoDay(new Date(y, m - 1, d - DEFAULT_DAYS, 12));
}

/**
 * "Erzwungene Status" (specs 001651, 001652): the forced status changes of a period,
 * counted per reason and per path (from state, to state), the largest count first. A
 * click on a count lists the applications behind it. A forced change from before the
 * reason list counts as "Ohne Grund". The page needs `audit.read`.
 */
@Component({
  selector: 'app-forced-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    BreadcrumbsComponent,
    ButtonComponent,
    CellDirective,
    DataTableComponent,
    DatepickerComponent,
    DialogComponent,
    EmptyStateComponent,
    PageHeaderComponent,
    SectionComponent,
  ],
  templateUrl: './forced-status.component.html',
  styleUrl: './forced-status.component.scss',
})
export class ForcedStatusComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);

  readonly to = signal(localToday());
  readonly from = signal(defaultFrom(localToday()));
  readonly report = signal<ForcedReport | null>(null);
  readonly loading = signal(true);
  readonly failed = signal(false);

  /** The open list behind a count. */
  readonly listRow = signal<CountRow | null>(null);
  readonly events = signal<ForcedEvent[]>([]);
  readonly eventsLoading = signal(false);

  readonly periodError = computed(() =>
    this.from() && this.to() && this.from() > this.to()
      ? this.i18n.translate('admin.forced.periodInvalid')
      : '',
  );

  readonly reasonColumns = computed<ColumnDef[]>(() => [
    { key: 'label', label: this.i18n.translate('admin.forced.col.reason'), card: 'title' },
    { key: 'count', label: this.i18n.translate('admin.forced.col.count'), align: 'end', width: '7rem' },
  ]);

  readonly pathColumns = computed<ColumnDef[]>(() => [
    { key: 'label', label: this.i18n.translate('admin.forced.col.path'), card: 'title' },
    { key: 'count', label: this.i18n.translate('admin.forced.col.count'), align: 'end', width: '7rem' },
  ]);

  readonly reasonRows = computed<CountRow[]>(() =>
    (this.report()?.byReason ?? []).map((r) => ({
      key: `reason:${r.reason}`,
      label: this.reasonLabel(r.reason),
      count: r.count,
      filter: { reason: r.reason },
    })),
  );

  readonly pathRows = computed<CountRow[]>(() => {
    const lang = this.i18n.uiLocale();
    const none = this.i18n.translate('admin.forced.noState');
    return (this.report()?.byPath ?? []).map((p) => ({
      key: `path:${p.fromKey ?? ''}:${p.toKey}`,
      label: `${p.fromKey ? i18nLabel(p.fromLabel, lang, p.fromKey) : none} → ${i18nLabel(p.toLabel, lang, p.toKey)}`,
      count: p.count,
      filter: { fromKey: p.fromKey ?? '', toKey: p.toKey },
    }));
  });

  private seq = 0;

  constructor() {
    this.load();
  }

  /** The label of a reason key; an unknown or missing key reads "Ohne Grund". */
  reasonLabel(reason: string): string {
    const known: readonly string[] = FORCE_REASONS;
    return this.i18n.translate(
      (known.includes(reason)
        ? `applications.forceReason.${reason}`
        : 'applications.forceReason.none') as TranslationKey,
    );
  }

  /** Set a bound of the period and load again. */
  setFrom(value: string): void {
    this.from.set(value);
    this.load();
  }

  setTo(value: string): void {
    this.to.set(value);
    this.load();
  }

  load(): void {
    if (this.periodError()) return;
    this.seq = this.seq + 1;
    const seq = this.seq;
    this.loading.set(true);
    this.failed.set(false);
    this.api.forcedReport({ from: this.from() || undefined, to: this.to() || undefined }).subscribe({
      next: (report) => {
        if (seq !== this.seq) return;
        this.report.set(report);
        this.loading.set(false);
      },
      error: () => {
        if (seq !== this.seq) return;
        this.report.set(null);
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Open the list of the applications behind a count. */
  openList(row: CountRow): void {
    this.listRow.set(row);
    this.events.set([]);
    this.eventsLoading.set(true);
    this.api
      .forcedEvents({ from: this.from() || undefined, to: this.to() || undefined, ...row.filter })
      .subscribe({
        next: (events) => {
          this.events.set(events);
          this.eventsLoading.set(false);
        },
        error: () => this.eventsLoading.set(false),
      });
  }

  closeList(): void {
    this.listRow.set(null);
  }

  /** "In Prüfung → Bewilligt" of one event. */
  pathOf(e: ForcedEvent): string {
    const lang = this.i18n.uiLocale();
    const none = this.i18n.translate('admin.forced.noState');
    return `${i18nLabel(e.fromLabel, lang, '') || none} → ${i18nLabel(e.toLabel, lang, '')}`;
  }

  titleOf(e: ForcedEvent): string {
    return e.title || this.i18n.translate('applications.list.untitled');
  }

  asRow(row: unknown): CountRow {
    return row as CountRow;
  }
}
