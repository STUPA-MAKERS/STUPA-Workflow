import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { type Observable, map, of, switchMap } from 'rxjs';
import {
  type EventDetail,
  type EventOption,
  EventsApiService,
} from '@core/api/events.service';
import { StatusCatalog } from '@core/api/statuses.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type FormDef, ToastService } from '@stupa-makers/ui-kit';
import { FormScreenComponent, type FormValue } from '@stupa-makers/ui-kit/screens';
import { NEW_SERIES, eventBody, eventFormValue, followUpValue } from './events.util';
import { EventsRefresh } from './events-refresh';

/** The refusals of the server that belong to one field of the form. */
const FIELD_ERROR: Readonly<Record<string, readonly [string, TranslationKey]>> = {
  event_url_invalid: ['shopUrl', 'events.error.url'],
  event_dates_invalid: ['endsOn', 'events.error.dates'],
  event_time_without_date: ['startTime', 'events.error.timeWithoutDate'],
  event_team_forbidden: ['teamId', 'events.error.team'],
  series_exists: ['seriesName', 'events.error.seriesExists'],
};

/**
 * "Veranstaltung anlegen" and "Veranstaltung bearbeiten" in the pane of the page
 * "Veranstaltungen" (specs 003023, 003027).
 *
 * The fields are the team of the person, the name, the status of the list `event`, the
 * description, the start and the end with their times, the place, the participants, the
 * series and the shop. The choice "Neue Reihe …" shows the field of its name, and the
 * save creates the series first. `?from=<id>` fills a new Event from another one
 * (`Folgeveranstaltung anlegen`, 003030): the name, the description, the place, the shop,
 * the team and the series, and no dates and no status.
 */
@Component({
  selector: 'app-event-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, FormScreenComponent],
  templateUrl: './event-form.component.html',
})
export class EventFormComponent {
  private readonly api = inject(EventsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly refresh = inject(EventsRefresh);
  private readonly catalog = inject(StatusCatalog);
  private readonly statuses = this.catalog.list('event');

  /** The Event to change, or null for a new one. */
  protected readonly event = signal<EventDetail | null>(null);
  private readonly teams = signal<readonly EventOption[]>([]);
  private readonly series = signal<readonly EventOption[]>([]);
  protected readonly value = signal<FormValue>(eventFormValue(null));
  protected readonly saving = signal(false);
  protected readonly errors = signal<Readonly<Record<string, string>>>({});

  protected readonly editing = computed(() => this.event() !== null);
  protected readonly title = computed(() =>
    this.t(this.editing() ? 'events.dialog.edit' : 'events.dialog.create'),
  );

  protected readonly form = computed<FormDef>(() => {
    const t = this.t.bind(this);
    const newSeries = this.value()['seriesId'] === NEW_SERIES;
    const current = this.event();
    const teams =
      current && !this.teams().some((team) => team.id === current.teamId)
        ? [{ value: current.teamId, label: current.teamName ?? '' }]
        : [];
    return {
      sections: [
        {
          key: 'event',
          fields: [
            {
              key: 'teamId',
              kind: 'select',
              label: t('events.field.team'),
              required: true,
              options: [...teams, ...this.teams().map((team) => ({ value: team.id, label: team.name }))],
            },
            { key: 'title', kind: 'text', label: t('events.field.title'), required: true, maxLength: 300 },
            {
              key: 'status',
              kind: 'select',
              label: t('events.field.status'),
              required: true,
              options: this.statuses().map((s) => ({ value: s.key, label: this.catalog.name(s) })),
            },
            { key: 'startsOn', kind: 'date', label: t('events.field.startsOn'), width: 'half' },
            { key: 'startTime', kind: 'time', label: t('events.field.startTime'), width: 'half' },
            { key: 'endsOn', kind: 'date', label: t('events.field.endsOn'), width: 'half' },
            { key: 'endTime', kind: 'time', label: t('events.field.endTime'), width: 'half' },
            { key: 'place', kind: 'text', label: t('events.field.place'), maxLength: 300, width: 'half' },
            {
              key: 'participants',
              kind: 'number',
              label: t('events.field.participants'),
              min: 0,
              step: 1,
              width: 'half',
            },
            {
              key: 'seriesId',
              kind: 'select',
              label: t('events.field.series'),
              options: [
                { value: '', label: t('events.series.none') },
                ...this.series().map((s) => ({ value: s.id, label: s.name })),
                { value: NEW_SERIES, label: t('events.series.new') },
              ],
            },
            {
              key: 'seriesName',
              kind: 'text',
              label: t('events.field.seriesName'),
              required: newSeries,
              maxLength: 200,
              visible: newSeries,
            },
            { key: 'shopUrl', kind: 'url', label: t('events.field.shop'), maxLength: 2000 },
            { key: 'descriptionMd', kind: 'markdown', label: t('events.field.description') },
          ],
        },
      ],
    };
  });

  constructor() {
    this.api.teams().subscribe({
      next: (list) => {
        this.teams.set(list);
        const only = list.length === 1 && !this.event() && !this.value()['teamId'];
        if (only) this.value.update((v) => ({ ...v, teamId: list[0].id }));
      },
      error: () => undefined,
    });
    this.api.series().subscribe({ next: (list) => this.series.set(list), error: () => undefined });
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      const id = params.get('id');
      const from = this.route.snapshot.queryParamMap.get('from');
      this.event.set(null);
      this.errors.set({});
      this.value.set(this.emptyValue());
      if (id) {
        this.loadEvent(id, (event) => {
          this.event.set(event);
          this.value.set(eventFormValue(event));
        });
      } else if (from) {
        this.loadEvent(from, (event) => this.value.set({ ...followUpValue(event), status: this.startStatus() }));
      }
    });
  }

  /** The empty form: the one team of the person and the start status are set. */
  private emptyValue(): FormValue {
    const teams = this.teams();
    return {
      ...eventFormValue(null),
      teamId: teams.length === 1 ? teams[0].id : '',
      status: this.startStatus(),
    };
  }

  private startStatus(): string {
    return this.statuses()[0]?.key ?? '';
  }

  private loadEvent(id: string, done: (event: EventDetail) => void): void {
    this.api.get(id).subscribe({
      next: done,
      error: () => {
        this.toast.show(this.t('events.error.load'), 'error');
        this.close();
      },
    });
  }

  protected onValue(next: FormValue): void {
    this.errors.set({});
    this.value.set(next);
  }

  protected save(value: FormValue): void {
    if (this.saving()) return;
    const event = this.event();
    const picked = String(value['seriesId'] ?? '');
    const name = String(value['seriesName'] ?? '').trim();
    if (picked === NEW_SERIES && !name) return;
    this.saving.set(true);
    const series: Observable<string | null> =
      picked === NEW_SERIES ? this.api.createSeries(name).pipe(
            map((made) => {
              this.series.update((list) => [...list, made]);
              return made.id;
            }),
          ) : of(picked || null);
    series
      .pipe(
        switchMap((seriesId) => {
          if (picked === NEW_SERIES && seriesId) this.value.update((v) => ({ ...v, seriesId, seriesName: '' }));
          const body = eventBody(value, seriesId);
          return event ? this.api.update(event.id, event.version, body) : this.api.create(body);
        }),
      )
      .subscribe({
        next: (saved) => {
          this.saving.set(false);
          this.refresh.touch();
          void this.router.navigate(['/events', saved.id], { queryParams: { from: null }, queryParamsHandling: 'merge' });
        },
        error: (err: { error?: { code?: string } | null }) => {
          this.saving.set(false);
          this.refused(err.error?.code ?? '');
        },
      });
  }

  /** "Abbrechen": back to the Event, or to the list from a new one. */
  protected close(): void {
    const event = this.event();
    void this.router.navigate(event ? ['/events', event.id] : ['/events'], {
      queryParams: { from: null },
      queryParamsHandling: 'merge',
    });
  }

  private refused(code: string): void {
    const field = FIELD_ERROR[code];
    if (field) {
      this.errors.set({ [field[0]]: this.t(field[1]) });
      return;
    }
    this.toast.show(this.t(code === 'event_version_conflict' ? 'events.error.version' : 'events.error.save'), 'error');
    if (code === 'event_version_conflict') this.close();
  }

  private t(key: TranslationKey): string {
    return this.i18n.translate(key);
  }
}
