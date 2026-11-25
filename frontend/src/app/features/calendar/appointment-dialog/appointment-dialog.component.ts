import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { type Observable, forkJoin } from 'rxjs';
import { FormsModule } from '@angular/forms';
import {
  type Appointment,
  CalendarApiService,
  type CalendarPerson,
  type CalendarTeam,
} from '@core/api/calendar.service';
import { problemCode } from '@core/api/problem';
import { TeamsApiService } from '@core/api/teams.service';
import { TodosApiService } from '@core/api/todos.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { shortTime } from '@shared/date-format';
import {
  AvatarComponent,
  ButtonComponent,
  ChipComponent,
  DatepickerComponent,
  DialogComponent,
  InputComponent,
  SwitchComponent,
  TextareaComponent,
  TimeInputComponent,
  ToastService,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';
import { GremiumLogoComponent } from '../../gremien/gremium-logo/gremium-logo.component';
import {
  GremiumPersonPickerComponent,
  type PickerTeam,
  type PickerHit,
} from '../../gremien/gremium-person-picker/gremium-person-picker.component';
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
  calendar_team_forbidden: 'calendar.toast.teamForbidden',
  calendar_publish: 'calendar.toast.publishForbidden',
};

/**
 * The dialog "Termin anlegen" and "Termin bearbeiten" (§ 000715-000718, 001074).
 *
 * A Termin has a title, a start and an end, all-day or with times, and can have a place
 * and a description. It invites teams (the teams of the person, every team with
 * `calendar.manage`, spec 003069) and persons (a search over the names of the active accounts), both in the one search
 * field of the shared picker, with the hits in a popover. The switch "Für alle
 * sichtbar" shows only with the permission `calendar.publish`. The server checks every
 * rule again.
 */
@Component({
  selector: 'app-appointment-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    FormsModule,
    AvatarComponent,
    ButtonComponent,
    ChipComponent,
    DatepickerComponent,
    DialogComponent,
    GremiumLogoComponent,
    GremiumPersonPickerComponent,
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
  private readonly teamsApi = inject(TeamsApiService);
  private readonly todos = inject(TodosApiService);
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
  readonly teams = signal<readonly CalendarTeam[]>([]);
  readonly persons = signal<readonly CalendarPerson[]>([]);
  readonly saving = signal(false);

  /** The teams that the person can invite: the own ones, every team with `calendar.manage`. */
  readonly known = signal<readonly PickerTeam[]>([]);
  /** The invited teams and persons: they leave the hits of the picker. */
  readonly taken = computed(() => [...this.teams().map((g) => g.id), ...this.persons().map((p) => p.id)]);
  /** The search of the persons of the picker: the names of the active accounts. */
  readonly findPeople = (q: string): Observable<readonly CalendarPerson[]> => this.api.people(q);

  readonly canPublish = computed(() => this.auth.can('calendar.publish'));
  readonly editing = computed(() => this.appointment() !== null);
  readonly valid = computed(() => formError(this.form()) === null);

  /** Each opening starts from the Termin, or from an empty form on the picked day. */
  constructor() {
    effect(() => {
      if (!this.open()) return;
      const current = this.appointment();
      const day = this.day();
      untracked(() => {
        this.form.set(current ? formOf(current) : emptyForm(day));
        this.teams.set(current?.teams ?? []);
        this.persons.set(current?.persons ?? []);
        this.loadTeams();
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

  /** A pick of the picker: a team or a person joins the invited. */
  addHit(hit: PickerHit): void {
    if (hit.kind === 'team') this.teams.update((list) => [...list, { id: hit.id, name: hit.name }]);
    else this.persons.update((list) => [...list, { id: hit.id, name: hit.name }]);
  }

  /** The logo of an invited team, when the list of the picker knows it. */
  logoOf(id: string): string | null {
    return this.known().find((g) => g.id === id)?.logoUrl ?? null;
  }

  removeTeam(id: string): void {
    this.teams.update((list) => list.filter((g) => g.id !== id));
  }

  removePerson(id: string): void {
    this.persons.update((list) => list.filter((p) => p.id !== id));
  }

  submit(): void {
    if (!this.valid() || this.saving()) return;
    const body = toInput(
      this.form(),
      this.teams().map((g) => g.id),
      this.persons().map((p) => p.id),
    );
    const current = this.appointment();
    this.saving.set(true);
    (current ? this.api.update(current.id, body) : this.api.create(body)).subscribe({
      next: (result) => {
        this.saving.set(false);
        this.toast.show(
          this.i18n.translate(current ? 'calendar.toast.saved' : 'calendar.toast.created'),
          'success',
        );
        this.saved.emit(result);
      },
      error: (err: unknown) => {
        this.saving.set(false);
        this.toast.show(
          this.i18n.translate(SAVE_ERRORS[problemCode(err)] ?? 'calendar.toast.saveFailed'),
          'error',
        );
      },
    });
  }

  private loadTeams(): void {
    const all = this.auth.can('calendar.manage');
    forkJoin([this.todos.entryOptions(), this.teamsApi.list()]).subscribe({
      next: ([options, teams]) => {
        const own = new Set(teams.filter((t) => t.isMember).map((t) => t.id));
        this.known.set(options.teams.filter((t) => all || own.has(t.id)));
      },
      error: () => this.known.set([]),
    });
  }
}
