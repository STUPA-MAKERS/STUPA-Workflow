import { ChangeDetectionStrategy, Component, computed, inject, linkedSignal, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import {
  type EventDecision,
  type EventDetail,
  type EventEdition,
  type EventStatus,
  EventsApiService,
} from '@core/api/events.service';
import { StatusCatalog } from '@core/api/statuses.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { dayMonthYear } from '@shared/date-format';
import { formatMoney } from '@shared/format-money';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import {
  type Action,
  ConfirmDialogComponent,
  FieldGroupComponent,
  FieldRowComponent,
  IconComponent,
  ListItemComponent,
  type LoadState,
  NoteComponent,
  type ScreenHead,
  SectionComponent,
  SelectFieldComponent,
  type SelectFieldOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { DetailScreenComponent, ScreenBodyDirective } from '@stupa-makers/ui-kit/screens';
import { TodoLinkedListComponent } from '../../features/todos/linked-list/todo-linked-list.component';
import { eventDays } from '../../features/todos/todos.util';
import { pageItemTitle } from '../../layout/page-title.service';
import { eventWhen } from './events.util';
import { EventsRefresh } from './events-refresh';

/** One field of the detail. `href` makes the value a link to another site. */
export interface EventFact {
  readonly label: string;
  readonly value: string;
  readonly href?: string;
}

/**
 * The detail of one Event in the pane of the page "Veranstaltungen" (spec 003029).
 *
 * In this order: the head with the name, the number and the status; "Bearbeiten",
 * "Folgeveranstaltung anlegen" (003030) and "Löschen" in the ⋮ menu; the field "Status" as
 * a dropdown of the list `event` that saves a pick at once (003042); the fields (003023)
 * with the shop as a link that opens a new tab (003024); the totals (000479); the
 * decisions (000482); the other Events of the series and how many of them the person does
 * not read (000483); the list "Verknüpft". Only a member of the team reads an Event, so
 * every person who sees the detail may change it (003026).
 */
@Component({
  selector: 'app-event-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ConfirmDialogComponent,
    DetailScreenComponent,
    FieldGroupComponent,
    FieldRowComponent,
    IconComponent,
    ListItemComponent,
    MarkdownViewComponent,
    NoteComponent,
    ScreenBodyDirective,
    SectionComponent,
    SelectFieldComponent,
    TodoLinkedListComponent,
  ],
  templateUrl: './event-detail.component.html',
})
export class EventDetailComponent {
  private readonly api = inject(EventsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly refresh = inject(EventsRefresh);
  private readonly catalog = inject(StatusCatalog);
  private readonly statuses = this.catalog.list('event');

  protected readonly event = signal<EventDetail | null>(null);
  private readonly failed = signal(false);
  protected readonly busy = signal(false);
  protected readonly deleting = signal(false);
  private id = '';

  protected readonly state = computed<LoadState<EventDetail>>(() => {
    const event = this.event();
    if (event) return { state: 'ready', data: event };
    return this.failed()
      ? { state: 'error', message: this.t('events.error.load'), retry: () => this.load() }
      : { state: 'loading' };
  });

  protected readonly head = computed<ScreenHead>(() => {
    const event = this.event();
    if (!event) return { title: this.t('nav.events'), back: null };
    return {
      title: event.title,
      kicker: event.number,
      status: {
        label: this.catalog.label('event', event.status),
        kind: this.catalog.tone('event', event.status),
      },
      back: null,
    };
  });

  /** The statuses of the list `event`, in the order of the list (003042). */
  protected readonly statusOptions = computed<readonly SelectFieldOption[]>(() =>
    this.statuses().map((s) => ({ value: s.key, label: this.catalog.name(s) })),
  );

  /** The pick of the field "Status"; it goes back to the saved status after a failed save. */
  protected readonly statusPick = linkedSignal(() => this.event()?.status ?? '');

  protected readonly actions = computed<readonly Action[]>(() => {
    const event = this.event();
    if (!event) return [];
    return [
      {
        key: 'edit',
        label: this.t('action.edit'),
        icon: 'edit',
        priority: 'head',
        route: { commands: ['/events', event.id, 'edit'] },
      },
      {
        key: 'followUp',
        label: this.t('events.menu.followUp'),
        icon: 'repeat',
        priority: 'menu',
        route: { commands: ['/events', 'new'], query: { from: event.id } },
      },
      { key: 'delete', label: this.t('action.delete'), icon: 'trash', kind: 'danger', priority: 'menu' },
    ];
  });

  /** The fields of 003023 that the Event has; the head shows the name, number and status. */
  protected readonly facts = computed<readonly EventFact[]>(() => {
    const e = this.event();
    if (!e) return [];
    const locale = this.i18n.formatLocale();
    const facts: (EventFact | null)[] = [
      e.teamName ? { label: this.t('events.field.team'), value: e.teamName } : null,
      e.startsOn
        ? { label: this.t('events.field.startsOn'), value: eventWhen(e, locale) ?? '' }
        : null,
      e.place ? { label: this.t('events.field.place'), value: e.place } : null,
      e.participants !== null
        ? { label: this.t('events.field.participants'), value: String(e.participants) }
        : null,
      e.seriesName ? { label: this.t('events.field.series'), value: e.seriesName } : null,
      e.shopUrl ? { label: this.t('events.field.shop'), value: e.shopUrl, href: e.shopUrl } : null,
    ];
    return facts.filter((f): f is EventFact => f !== null);
  });

  /** Requested, approved, expenses, income and the signed balance (000479). */
  protected readonly totals = computed(() => {
    const totals = this.event()?.totals;
    if (!totals) return [];
    const lines: readonly [TranslationKey, string, boolean][] = [
      ['events.money.requested', totals.requested, false],
      ['events.money.approved', totals.approved, false],
      ['events.money.expenses', totals.expenses, false],
      ['events.money.income', totals.income, false],
      ['events.money.balance', totals.balance, true],
    ];
    return lines.map(([key, amount, signed]) => ({ label: this.t(key), value: this.money(amount, signed) }));
  });

  constructor() {
    pageItemTitle(() => this.event()?.title);
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      this.id = params.get('id') ?? '';
      this.event.set(null);
      this.load();
    });
  }

  private load(): void {
    const id = this.id;
    this.failed.set(false);
    this.api.get(id).subscribe({
      next: (event) => id === this.id && this.event.set(event),
      error: () => {
        if (id === this.id) this.failed.set(true);
      },
    });
  }

  protected onAction(key: string): void {
    if (key === 'delete') this.deleting.set(true);
  }

  protected setStatus(status: EventStatus): void {
    const event = this.event();
    if (!event || this.busy() || status === event.status) return;
    this.busy.set(true);
    this.api.setStatus(event.id, status, event.version).subscribe({
      next: (saved) => {
        this.busy.set(false);
        this.event.set(saved);
        this.refresh.touch();
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.busy.set(false);
        this.statusPick.set(event.status);
        const stale = err.error?.code === 'event_version_conflict';
        this.toast.show(this.t(stale ? 'events.error.version' : 'events.error.save'), 'error');
        if (stale) this.load();
      },
    });
  }

  protected confirmDelete(): void {
    const event = this.event();
    if (!event || this.busy()) return;
    this.busy.set(true);
    this.api.remove(event.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.deleting.set(false);
        this.refresh.touch();
        void this.router.navigate(['/events'], { queryParamsHandling: 'preserve' });
      },
      error: () => {
        this.busy.set(false);
        this.deleting.set(false);
        this.toast.show(this.t('events.error.delete'), 'error');
      },
    });
  }

  protected decisionLink(d: EventDecision): readonly string[] | null {
    if (!d.targetId) return null;
    return d.kind === 'vote' ? ['/voting', d.targetId] : ['/applications', d.targetId];
  }

  /** "Title: angenommen". */
  protected decisionTitle(d: EventDecision): string {
    const key = `vote.result.${d.result}` as TranslationKey;
    const result = d.result ? this.t(key) : '';
    return result && result !== key ? `${d.title}: ${result}` : d.title;
  }

  /** "StuPa 3 · 01.11.2026 · 500,00 € · Auflage: …". */
  protected decisionSub(d: EventDecision): string {
    const locale = this.i18n.formatLocale();
    return [
      d.meetingTitle,
      d.decidedAt ? dayMonthYear(d.decidedAt, locale) : null,
      d.amount ? formatMoney(d.amount, locale) : null,
      ...d.conditions.map((text) => this.t('events.decisions.condition', { text })),
    ]
      .filter(Boolean)
      .join(' · ');
  }

  /** "20.11.2026 · Abgerechnet · Saldo +312,00 €". */
  protected editionSub(e: EventEdition): string {
    return [
      eventDays(e.startsOn, e.endsOn, this.i18n.formatLocale()),
      this.catalog.label('event', e.status),
      this.t('events.editions.balance', { amount: this.money(e.totals.balance, true) }),
    ]
      .filter(Boolean)
      .join(' · ');
  }

  private money(value: string, signed = false): string {
    return formatMoney(value, this.i18n.formatLocale(), { signed });
  }

  private t(key: TranslationKey, params?: Record<string, string | number>): string {
    return this.i18n.translate(key, params);
  }
}
