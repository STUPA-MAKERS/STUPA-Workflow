import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { FORCE_REASONS, type ForcedEvent, type ForcedPathCount } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { isoDay, localToday } from '@shared/date-format';
import { i18nLabel } from '@shared/forms/i18n-text';
import type { LoadState } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';
import {
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  ListItemComponent,
  PageHeaderComponent,
  RangeChipComponent,
  type RangeValue,
  SkeletonComponent,
  StickyBarComponent,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';

/** The default period: the last 90 days (spec 001651, as the server). */
export const DEFAULT_DAYS = 90;

/** The first day of the default period: `DEFAULT_DAYS` before `today`. */
export function defaultFrom(today: string): string {
  const [y, m, d] = today.split('-').map(Number);
  return isoDay(new Date(y, m - 1, d - DEFAULT_DAYS, 12));
}

/** The filter value of a path: `<from key>><to key>`, an empty from key for no state. */
export function pathValue(fromKey: string | null, toKey: string): string {
  return `${fromKey ?? ''}>${toKey}`;
}

/**
 * "Erzwungene Status" (specs 001651, 001652): one list of the forced status changes, the
 * newest first, with filters for the reason, the path (from state, to state) and the
 * period (the last 90 days by default). A row opens the application. A forced change from
 * before the reason list reads "Ohne Grund". The page needs `audit.read`.
 */
@Component({
  selector: 'app-forced-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    LocalizedDatePipe,
    BreadcrumbsComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    ListItemComponent,
    LoadStateComponent,
    PageHeaderComponent,
    RangeChipComponent,
    SkeletonComponent,
    StickyBarComponent,
  ],
  templateUrl: './forced-status.component.html',
  styleUrl: './forced-status.component.scss',
})
export class ForcedStatusComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);

  readonly to = signal(localToday());
  readonly from = signal(defaultFrom(localToday()));
  readonly reason = signal('');
  readonly path = signal('');
  readonly paths = signal<readonly ForcedPathCount[]>([]);
  readonly events = signal<readonly ForcedEvent[]>([]);
  readonly loading = signal(true);
  readonly failed = signal(false);

  readonly reasonOptions = computed<FilterSelectOption[]>(() =>
    [...FORCE_REASONS, 'none'].map((r) => ({ value: r, label: this.reasonLabel(r) })),
  );

  /** The paths of the period, from the report of the server. */
  readonly pathOptions = computed<FilterSelectOption[]>(() =>
    this.paths().map((p) => ({ value: pathValue(p.fromKey, p.toKey), label: this.pathLabel(p) })),
  );

  readonly reasonText = computed(
    () => this.reasonOptions().find((o) => o.value === this.reason())?.label ?? null,
  );
  readonly pathText = computed(
    () => this.pathOptions().find((o) => o.value === this.path())?.label ?? null,
  );
  readonly filtered = computed(() => !!this.reason() || !!this.path());
  /** The first load shows skeleton rows; a reload keeps the list. */
  readonly loadState = computed<LoadState>(() =>
    this.failed() ? 'error' : this.loading() && !this.events().length ? 'loading' : 'ok',
  );

  private seq = 0;

  constructor() {
    this.loadPaths();
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

  setReason(value: string | readonly string[]): void {
    this.reason.set(typeof value === 'string' ? value : (value[0] ?? ''));
    this.load();
  }

  setPath(value: string | readonly string[]): void {
    this.path.set(typeof value === 'string' ? value : (value[0] ?? ''));
    this.load();
  }

  /** The period chip sets both days at once; an empty day falls back to the default. */
  setRange(v: RangeValue): void {
    this.from.set(v.from || defaultFrom(localToday()));
    this.to.set(v.to || localToday());
    this.path.set('');
    this.loadPaths();
    this.load();
  }

  private range(): { from: string; to: string } {
    return { from: this.from(), to: this.to() };
  }

  private loadPaths(): void {
    this.api.forcedReport(this.range()).subscribe({
      next: (report) => this.paths.set(report.byPath),
      error: () => this.paths.set([]),
    });
  }

  load(): void {
    this.seq = this.seq + 1;
    const seq = this.seq;
    const [fromKey, toKey] = this.path() ? this.path().split('>') : [undefined, undefined];
    this.loading.set(true);
    this.failed.set(false);
    this.api
      .forcedEvents({ ...this.range(), reason: this.reason() || undefined, fromKey, toKey })
      .subscribe({
        next: (events) => {
          if (seq !== this.seq) return;
          this.events.set(events);
          this.loading.set(false);
        },
        error: () => {
          if (seq !== this.seq) return;
          this.events.set([]);
          this.failed.set(true);
          this.loading.set(false);
        },
      });
  }

  private pathLabel(p: ForcedPathCount): string {
    const lang = this.i18n.uiLocale();
    const none = this.i18n.translate('admin.forced.noState');
    return `${p.fromKey ? i18nLabel(p.fromLabel, lang, p.fromKey) : none} → ${i18nLabel(p.toLabel, lang, p.toKey)}`;
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
}
