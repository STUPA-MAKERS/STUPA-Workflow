import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  type ExternalCalendar,
  type ExternalCalendarInput,
  ExternalCalendarsApiService,
  FETCH_INTERVALS,
  type FetchInterval,
} from '@core/api/calendar.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ExpandRowComponent } from '@shared/ui/expand-row/expand-row.component';
import { LoadStateComponent, loadStateOf } from '@shared/ui/load-state/load-state.component';
import {
  ButtonComponent,
  ConfirmDialogComponent,
  DialogComponent,
  EmptyStateComponent,
  FabComponent,
  InputComponent,
  PageHeaderComponent,
  RowMenuComponent,
  type RowMenuSection,
  SectionComponent,
  SegmentedComponent,
  SelectFieldComponent,
  type SelectOption,
  SkeletonComponent,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { AdminOptionsService } from '../admin-options.service';

/** The scope choice of the dialog. */
type Scope = 'all' | 'gremium';

/** The fields of the dialog. `id` is null for a new calendar. */
interface Draft {
  readonly id: string | null;
  readonly name: string;
  readonly url: string;
  readonly scope: Scope;
  readonly gremiumId: string;
  readonly interval: string;
}

/** The state of the newest fetch as status text. */
interface FetchState {
  readonly kind: 'accent' | 'error' | 'muted';
  readonly key: TranslationKey;
}

/** The client check of the address: `https://` with something after it, no blank. */
const HTTPS_URL = /^https:\/\/\S+$/;

const EMPTY: Draft = { id: null, name: '', url: '', scope: 'all', gremiumId: '', interval: '60' };

/** The fetch state of a calendar: failed, fetched, or not fetched yet. */
export function fetchState(calendar: ExternalCalendar): FetchState {
  if (calendar.lastError) return { kind: 'error', key: 'admin.calendars.state.failed' };
  return calendar.lastSuccessAt
    ? { kind: 'accent', key: 'admin.calendars.state.ok' }
    : { kind: 'muted', key: 'admin.calendars.state.pending' };
}

function draftOf(calendar: ExternalCalendar): Draft {
  return {
    id: calendar.id,
    name: calendar.name,
    url: calendar.url,
    scope: calendar.gremiumId ? 'gremium' : 'all',
    gremiumId: calendar.gremiumId ?? '',
    interval: String(calendar.intervalMinutes),
  };
}

function inputOf(draft: Draft): ExternalCalendarInput {
  return {
    name: draft.name.trim(),
    url: draft.url.trim(),
    gremiumId: draft.scope === 'gremium' ? draft.gremiumId : null,
    intervalMinutes: Number(draft.interval) as FetchInterval,
  };
}

/** Returns `list` with `saved` in place of the calendar of its id, or at the end. */
function withSaved(
  list: readonly ExternalCalendar[],
  saved: ExternalCalendar,
): readonly ExternalCalendar[] {
  return list.some((c) => c.id === saved.id)
    ? list.map((c) => (c.id === saved.id ? saved : c))
    : [...list, saved];
}

/**
 * The admin page `Kalender` at `/admin/calendars` (§F/meetings/calendar/000729): the
 * external calendars that the platform reads. One expand row per calendar: the name with
 * the state of its newest fetch as status text, then the scope, the interval and the
 * whole address as the sub line, and the ⋮ menu with "Jetzt abrufen", "Bearbeiten" and
 * "Löschen". A press on the row opens the edit. The chevron opens the body "Abruf":
 * state, newest attempt, newest success, number of entries and the reason of a failure.
 *
 * Create and edit run in a dialog. It refuses an address that does not start with
 * `https://`, because the server fetches only over https. The server never fetches in a
 * request: a save of the address and "Jetzt abrufen" make the calendar due, and the
 * worker fetches it within a minute. Every route needs P(`admin.calendars`), which the
 * backend enforces; the route gate keeps other persons off the page.
 */
@Component({
  selector: 'app-admin-calendars',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    LoadStateComponent,
    ExpandRowComponent,
    BreadcrumbsComponent,
    ButtonComponent,
    ConfirmDialogComponent,
    DialogComponent,
    EmptyStateComponent,
    FabComponent,
    InputComponent,
    PageHeaderComponent,
    RowMenuComponent,
    SectionComponent,
    SegmentedComponent,
    SelectFieldComponent,
    SkeletonComponent,
    StatusTextComponent,
  ],
  templateUrl: './calendars.component.html',
  styleUrl: '../webhooks/webhooks.component.scss',
})
export class AdminCalendarsComponent {
  private readonly api = inject(ExternalCalendarsApiService);
  private readonly options = inject(AdminOptionsService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  /** True until the first answer, so the page never shows "none" before it knows. */
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly loadState = loadStateOf(this.loading, this.loadError);

  protected readonly calendars = signal<readonly ExternalCalendar[]>([]);
  protected readonly gremien = signal<readonly SelectOption[]>([]);
  /** The calendar whose fetch details are open. */
  protected readonly openId = signal<string | null>(null);
  protected readonly draft = signal<Draft | null>(null);
  protected readonly saving = signal(false);
  /** The calendar whose delete the person confirms now. */
  protected readonly confirmDelete = signal<ExternalCalendar | null>(null);

  protected readonly scopeOptions = computed<readonly SelectOption[]>(() => [
    { value: 'all', label: this.i18n.translate('admin.calendars.scope.all') },
    { value: 'gremium', label: this.i18n.translate('admin.calendars.scope.gremium') },
  ]);
  protected readonly intervalOptions = computed<readonly SelectOption[]>(() =>
    FETCH_INTERVALS.map((minutes) => ({
      value: String(minutes),
      label: this.intervalLabel(minutes),
    })),
  );
  protected readonly rowMenu = computed<readonly RowMenuSection[]>(() => [
    {
      items: [
        { id: 'fetch', label: this.i18n.translate('admin.calendars.fetchNow'), icon: 'repeat' },
        { id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' },
      ],
    },
    {
      items: [
        { id: 'delete', label: this.i18n.translate('admin.common.remove'), icon: 'trash', danger: true },
      ],
    },
  ]);

  /** The address error of the dialog, shown once the field holds something. */
  protected readonly urlError = computed(() => {
    const d = this.draft();
    return d && d.url.trim() && !HTTPS_URL.test(d.url.trim()) ? 'admin.calendars.badUrl' : '';
  });
  protected readonly canSave = computed(() => {
    const d = this.draft();
    return (
      !!d &&
      !this.saving() &&
      d.name.trim().length > 0 &&
      HTTPS_URL.test(d.url.trim()) &&
      (d.scope === 'all' || d.gremiumId !== '')
    );
  });

  constructor() {
    this.load();
    this.options.gremiumOptions().subscribe({
      next: (list) => this.gremien.set(list),
      error: () => this.gremien.set([]),
    });
  }

  /** Read the calendars; also the retry of the load error. */
  protected load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.list().subscribe({
      next: (list) => {
        this.calendars.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  protected tr(key: string): string {
    return this.i18n.translate(key as TranslationKey);
  }

  protected state(calendar: ExternalCalendar): FetchState {
    return fetchState(calendar);
  }

  protected intervalLabel(minutes: number): string {
    return this.tr(`admin.calendars.interval.${minutes}`);
  }

  /** The scope of a calendar: "Alle" or the name of its Gremium. */
  protected scopeLabel(calendar: ExternalCalendar): string {
    return calendar.gremiumName ?? this.i18n.translate('admin.calendars.scope.all');
  }

  /** The reason of a failure as a sentence. An unknown code of a newer backend reads raw. */
  protected reasonLabel(code: string | null): string {
    if (!code) return '—';
    const key = `admin.calendars.reason.${code}`;
    const label = this.tr(key);
    return label === key ? code : label;
  }

  protected toggle(calendar: ExternalCalendar): void {
    this.openId.update((id) => (id === calendar.id ? null : calendar.id));
  }

  protected openAdd(): void {
    this.draft.set(EMPTY);
  }

  protected openEdit(calendar: ExternalCalendar): void {
    this.draft.set(draftOf(calendar));
  }

  protected close(): void {
    this.draft.set(null);
  }

  protected patch<K extends keyof Draft>(key: K, value: Draft[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  protected save(): void {
    const d = this.draft();
    if (!d || !this.canSave()) return;
    this.saving.set(true);
    const body = inputOf(d);
    (d.id ? this.api.update(d.id, body) : this.api.create(body)).subscribe({
      next: (saved) => {
        this.calendars.update((list) => withSaved(list, saved));
        this.saving.set(false);
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.close();
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  protected onMenu(action: string, calendar: ExternalCalendar): void {
    switch (action) {
      case 'fetch':
        return this.fetchNow(calendar);
      case 'edit':
        return this.openEdit(calendar);
      default:
        return this.confirmDelete.set(calendar);
    }
  }

  private fetchNow(calendar: ExternalCalendar): void {
    this.api.fetchNow(calendar.id).subscribe({
      next: (saved) => {
        this.calendars.update((list) => withSaved(list, saved));
        this.toast.success(this.i18n.translate('admin.calendars.fetchRequested'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.calendars.fetchFailed')),
    });
  }

  protected doDelete(): void {
    const calendar = this.confirmDelete();
    if (!calendar) return;
    this.api.remove(calendar.id).subscribe({
      next: () => {
        this.calendars.update((list) => list.filter((c) => c.id !== calendar.id));
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.calendars.deleted'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.calendars.deleteFailed')),
    });
  }
}
