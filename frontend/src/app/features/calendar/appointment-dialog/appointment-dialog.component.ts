import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import {
  type Appointment,
  CalendarApiService,
  type CalendarGremium,
  type CalendarPerson,
} from '@core/api/calendar.service';
import { problemCode } from '@core/api/problem';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { shortTime } from '@shared/date-format';
import {
  AutocompleteComponent,
  AvatarComponent,
  ButtonComponent,
  ChipComponent,
  DatepickerComponent,
  DialogComponent,
  FilterSelectComponent,
  IconComponent,
  InputComponent,
  SwitchComponent,
  TextareaComponent,
  TimeInputComponent,
  ToastService,
  liveSearch,
} from '@stupa-makers/ui-kit';
import { type AppointmentForm, emptyForm, formError, toInput } from '../calendar.util';

/** The form of an existing Termin. */
function formOf(a: Appointment): AppointmentForm {
  return {
    title: a.title,
    allDay: a.startTime === null,
    startsOn: a.startsOn,
    endsOn: a.endsOn,
    startTime: a.startTime ? shortTime(a.startTime) : '09:00',
    endTime: a.endTime ? shortTime(a.endTime) : '10:00',
    place: a.place ?? '',
    description: a.description ?? '',
    forAll: a.forAll,
    public: a.public,
  };
}

/** The toast of a refused save, by the code of the server. */
const SAVE_ERRORS: Readonly<Record<string, TranslationKey>> = {
  calendar_gremium_forbidden: 'calendar.toast.gremiumForbidden',
  calendar_publish: 'calendar.toast.publishForbidden',
};

/**
 * The dialog "Termin anlegen" and "Termin bearbeiten" (§ 000715-000718, 000738).
 *
 * A Termin has a title, a start and an end, all-day or with times, and can have a place
 * and a description. It invites Gremien (the Gremien whose meetings the person reads)
 * and persons (a search over the names of the active accounts). The switch "Für alle
 * sichtbar" shows only with the permission `calendar.publish`. The server checks every
 * rule again.
 */
@Component({
  selector: 'app-appointment-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    AutocompleteComponent,
    AvatarComponent,
    ButtonComponent,
    ChipComponent,
    DatepickerComponent,
    DialogComponent,
    FilterSelectComponent,
    IconComponent,
    InputComponent,
    SwitchComponent,
    TextareaComponent,
    TimeInputComponent,
    TranslatePipe,
  ],
  templateUrl: './appointment-dialog.component.html',
  styleUrl: './appointment-dialog.component.scss',
})
export class AppointmentDialogComponent {
  private readonly api = inject(CalendarApiService);
  private readonly client = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input(false);
  /** The Termin to change, or null for a new one. */
  readonly appointment = input<Appointment | null>(null);
  /** The day of a new Termin. */
  readonly day = input('');

  readonly closed = output<void>();
  readonly saved = output<Appointment>();

  readonly form = signal<AppointmentForm>(emptyForm(''));
  readonly gremien = signal<readonly CalendarGremium[]>([]);
  readonly persons = signal<readonly CalendarPerson[]>([]);
  readonly saving = signal(false);

  /** The Gremien that the person can invite: those with a meeting that the person reads. */
  private readonly known = signal<readonly CalendarGremium[]>([]);
  readonly gremiumOptions = computed(() => {
    const invited = new Set(this.gremien().map((g) => g.id));
    return this.known()
      .filter((g) => !invited.has(g.id))
      .map((g) => ({ value: g.id, label: g.name }));
  });

  readonly canPublish = computed(() => this.auth.can('calendar.publish'));
  readonly editing = computed(() => this.appointment() !== null);
  readonly valid = computed(() => formError(this.form()) === null);

  readonly personQuery = signal('');
  readonly personHits = signal<readonly CalendarPerson[]>([]);
  readonly personSearch = liveSearch<readonly CalendarPerson[]>({
    run: (q) => this.api.people(q),
    result: (hits) => {
      const invited = new Set(this.persons().map((p) => p.id));
      this.personHits.set(hits.filter((p) => !invited.has(p.id)));
    },
    reset: () => this.personHits.set([]),
    error: () => this.personHits.set([]),
  });
  readonly personLabel = (p: CalendarPerson): string => p.name;

  /** Each opening starts from the Termin, or from an empty form on the picked day. */
  constructor() {
    effect(() => {
      if (!this.open()) return;
      const current = this.appointment();
      const day = this.day();
      untracked(() => {
        this.form.set(current ? formOf(current) : emptyForm(day));
        this.gremien.set(current?.gremien ?? []);
        this.persons.set(current?.persons ?? []);
        this.clearPersonSearch();
        this.loadGremien();
      });
    });
  }

  patch(change: Partial<AppointmentForm>): void {
    this.form.update((form) => ({ ...form, ...change }));
  }

  /** A start after the end moves the end, so the span stays valid while the person types. */
  setStart(day: string): void {
    this.form.update((form) => ({ ...form, startsOn: day, endsOn: form.endsOn < day ? day : form.endsOn }));
  }

  addGremium(id: string): void {
    const hit = this.known().find((g) => g.id === id);
    if (hit) this.gremien.update((list) => [...list, hit]);
  }

  removeGremium(id: string): void {
    this.gremien.update((list) => list.filter((g) => g.id !== id));
  }

  onPersonQuery(text: string): void {
    this.personQuery.set(text);
    this.personSearch.set(text);
  }

  addPerson(person: CalendarPerson): void {
    this.persons.update((list) => [...list, person]);
    this.clearPersonSearch();
  }

  removePerson(id: string): void {
    this.persons.update((list) => list.filter((p) => p.id !== id));
  }

  submit(): void {
    if (!this.valid() || this.saving()) return;
    const body = toInput(
      this.form(),
      this.gremien().map((g) => g.id),
      this.persons().map((p) => p.id),
    );
    const current = this.appointment();
    this.saving.set(true);
    (current ? this.api.update(current.id, body) : this.api.create(body)).subscribe({
      next: (result) => {
        this.saving.set(false);
        this.toast.success(this.i18n.translate(current ? 'calendar.toast.saved' : 'calendar.toast.created'));
        this.saved.emit(result);
      },
      error: (err: unknown) => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate(SAVE_ERRORS[problemCode(err)] ?? 'calendar.toast.saveFailed'));
      },
    });
  }

  private clearPersonSearch(): void {
    this.personQuery.set('');
    this.personHits.set([]);
    this.personSearch.sync('');
  }

  private loadGremien(): void {
    this.client.listMeetingFilterGremien().subscribe({
      next: (list) => this.known.set(list),
      error: () => this.known.set([]),
    });
  }
}
