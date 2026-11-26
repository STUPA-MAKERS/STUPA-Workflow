import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  EVENT_SEGMENTS,
  type EventItem,
  type EventOption,
  type EventQuery,
  type EventSegment,
  EventsApiService,
} from '@core/api/events.service';
import { StatusCatalog } from '@core/api/statuses.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  type Action,
  type FilterDef,
  type ListQuery,
  type ListRow,
  type LoadState,
  ToastService,
  downloadBlob,
} from '@stupa-makers/ui-kit';
import { ListDetailScreenComponent } from '@stupa-makers/ui-kit/screens';
import { SEGMENT_LABEL, eventQuery, eventWhen, isSegment } from './events.util';
import { EventsRefresh } from './events-refresh';

/** How many rows one read of the list brings. */
export const EVENTS_PAGE_SIZE = 50;

/**
 * The page "Veranstaltungen" (spec 003027): the Events of the teams of the person, as a
 * list with the detail beside it.
 *
 * The first chip picks the segment (003028): `Kommend` (the default), `Vergangen`,
 * `Erledigt` and `Verworfen`. No segment shows a count. The chips `Team` and `Reihe` and
 * the search filter the list, and all of them live in the URL. A row shows the name, the
 * status, the dates and the place, and opens the Event in the pane. The action
 * "Veranstaltung anlegen" shows for a member of a team, the export (003034) for a person
 * with `finance.export`.
 */
@Component({
  selector: 'app-events-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ListDetailScreenComponent],
  templateUrl: './events-page.component.html',
})
export class EventsPageComponent {
  private readonly api = inject(EventsApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly statuses = inject(StatusCatalog);

  private readonly teams = signal<readonly EventOption[]>([]);
  private readonly series = signal<readonly EventOption[]>([]);
  private readonly events = signal<readonly EventItem[]>([]);
  private readonly total = signal(0);
  private readonly phase = signal<'loading' | 'ready' | 'error'>('loading');
  private readonly segment = signal<EventSegment>('upcoming');
  private readonly filter = signal<EventQuery>({});
  /** Counts the reads, so an answer of an older filter is dropped. */
  private seq = 0;

  /** A member of a team creates an Event (003026). */
  protected readonly canCreate = computed(() => this.teams().length > 0);
  protected readonly canExport = computed(() => this.auth.can('finance.export'));

  protected readonly filters = computed<readonly FilterDef[]>(() => {
    const t = this.i18n.translate.bind(this.i18n);
    const option = (o: EventOption): { value: string; label: string } => ({ value: o.id, label: o.name });
    return [
      {
        key: 'segment',
        label: t('events.filter.segment'),
        kind: 'single',
        options: EVENT_SEGMENTS.map((value) => ({ value, label: t(SEGMENT_LABEL[value]) })),
        value: 'upcoming',
      },
      ...(this.teams().length > 1
        ? [{ key: 'team', label: t('events.filter.team'), kind: 'single', options: this.teams().map(option), value: null } as const]
        : []),
      ...(this.series().length
        ? [{ key: 'series', label: t('events.filter.series'), kind: 'single', options: this.series().map(option), value: null } as const]
        : []),
    ];
  });

  protected readonly actions = computed<readonly Action[]>(() => [
    ...(this.canCreate()
      ? [
          {
            key: 'new',
            label: this.i18n.translate('events.dialog.create'),
            icon: 'plus',
            priority: 'fab',
            route: { commands: ['/events', 'new'] },
          } as const,
        ]
      : []),
    ...(this.canExport()
      ? [
          {
            key: 'export',
            label: this.i18n.translate('events.page.export'),
            icon: 'download',
            priority: 'menu',
          } as const,
        ]
      : []),
  ]);

  protected readonly rows = computed<LoadState<readonly ListRow[]>>(() => {
    const rows = this.events().map((e) => this.row(e));
    switch (this.phase()) {
      case 'loading':
        return rows.length ? { state: 'loading', previous: rows } : { state: 'loading' };
      case 'error':
        return {
          state: 'error',
          message: this.i18n.translate('events.page.error'),
          retry: () => this.load(),
        };
      case 'ready':
        return rows.length
          ? { state: 'ready', data: rows, more: rows.length < this.total() }
          : { state: 'empty', heading: this.i18n.translate('events.page.empty'), icon: 'mappin' };
    }
  });

  constructor() {
    inject(EventsRefresh)
      .changed.pipe(takeUntilDestroyed())
      .subscribe(() => this.load());
    this.api.teams().subscribe({ next: (list) => this.teams.set(list), error: () => undefined });
    this.api.series().subscribe({ next: (list) => this.series.set(list), error: () => undefined });
  }

  protected onQuery(query: ListQuery): void {
    const wanted = query.filters['segment'];
    this.segment.set(isSegment(wanted) ? wanted : 'upcoming');
    this.filter.set(eventQuery(query));
    this.load();
  }

  protected onAction(key: string): void {
    if (key !== 'export') return;
    this.api.exportXlsx({ ...this.filter(), segment: this.segment() }).subscribe({
      next: (blob) => downloadBlob(blob, 'veranstaltungen.xlsx'),
      error: () => this.toast.show(this.i18n.translate('events.page.exportError'), 'error'),
    });
  }

  /** Read the next rows of the segment. */
  protected more(): void {
    this.load(this.events().length);
  }

  /** Read the segment with the filter; `offset` above 0 adds the next rows. */
  private load(offset = 0): void {
    this.seq += 1;
    const seq = this.seq;
    this.phase.set('loading');
    this.api
      .page({ ...this.filter(), segment: this.segment(), limit: EVENTS_PAGE_SIZE, offset })
      .subscribe({
        next: (page) => {
          if (seq !== this.seq) return;
          this.events.update((old) => (offset ? [...old, ...page.items] : page.items));
          this.total.set(page.total);
          this.phase.set('ready');
        },
        error: () => {
          if (seq === this.seq) this.phase.set('error');
        },
      });
  }

  private row(e: EventItem): ListRow {
    const when = eventWhen(e, this.i18n.formatLocale());
    return {
      id: e.id,
      title: e.title,
      meta: [when, e.place, e.teamName].filter((part): part is string => !!part),
      status: { label: this.statuses.label('event', e.status), kind: this.statuses.tone('event', e.status) },
      link: { commands: ['/events', e.id] },
    };
  }
}
