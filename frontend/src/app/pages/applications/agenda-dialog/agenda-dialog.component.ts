import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting, ProblemDetail, Transition, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { DateBlockComponent } from '@shared/ui/date-block/date-block.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';

/** A meeting row of the dialog. */
interface MeetingChoice {
  meeting: Meeting;
  /** "Di, 18:00 · 7 TOPs": the parts that exist, joined by a dot. */
  sub: string;
}

/** Today as a local `YYYY-MM-DD`, the shape of `Meeting.date`. */
function localToday(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * "Auf Tagesordnung setzen" (board Anträge-Tagesordnung): fire a transition with
 * `addsToAgenda` and choose the meeting whose agenda gets the application (A1).
 *
 * The dialog offers only the planned meetings of `agendaGremiumId`; the server takes no
 * other meeting (422 `agenda_meeting_invalid`). The first planned meeting from today on
 * is the suggestion ("Vorschlag"): the action picks the same one when a transition fires
 * without a meeting. "Nicht öffentlich" makes the new agenda item non-public; the note
 * goes into the history of the application.
 *
 * The reader sees only the meetings of the gremien they can see. When no planned meeting
 * is visible (the reader is not in the agenda gremium, the gremium has no planned
 * meeting, or the load failed), the dialog still fires the transition, but without a
 * meeting: the action of the server then picks the next planned meeting after the
 * commit, as before A1. "Nicht öffentlich" has no effect then, so the dialog hides it.
 *
 * The list page (row menu) and the detail (header) both open it; `done` fires after the
 * transition, and also after a 409, so the caller loads the application again.
 */
@Component({
  selector: 'app-agenda-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ScrollFadeDirective,
    FormsModule,
    TranslatePipe,
    DateBlockComponent,
    SkeletonComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    SwitchComponent,
  ],
  templateUrl: './agenda-dialog.component.html',
  styleUrl: './agenda-dialog.component.scss',
})
export class AgendaDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly applicationId = input<Uuid | null>(null);
  /** The title of the application, below the dialog title. */
  readonly applicationTitle = input('');
  /** The transition to fire. It must have `addsToAgenda`. */
  readonly transition = input<Transition | null>(null);
  readonly open = model(false);
  /** The transition fired, or the application changed meanwhile (409). */
  readonly done = output<void>();

  protected readonly loading = signal(false);
  protected readonly meetings = signal<Meeting[]>([]);
  protected readonly pick = signal<Uuid | null>(null);
  protected readonly nonPublic = signal(false);
  protected readonly note = signal('');
  protected readonly saving = signal(false);
  /** The reason the server refused the chosen meeting, shown in the dialog. */
  protected readonly refusal = signal<TranslationKey | null>(null);

  /** The first planned meeting from today on: the meeting the action would pick. */
  protected readonly suggestedId = computed(() => {
    const today = localToday();
    return this.meetings().find((m) => m.date !== null && m.date >= today)?.id ?? null;
  });

  protected readonly choices = computed<MeetingChoice[]>(() =>
    this.meetings().map((meeting) => ({ meeting, sub: this.subLine(meeting) })),
  );

  /** No planned meeting is visible: the transition fires without a meeting. */
  protected readonly noMeeting = computed(() => !this.loading() && this.choices().length === 0);

  /** The confirm button works: a meeting is chosen, or none is visible. */
  protected readonly canConfirm = computed(() => !this.loading() && (!!this.pick() || this.noMeeting()));

  /** The gremium of the meetings, at the end of the caption line. */
  protected readonly gremiumName = computed(() => this.meetings()[0]?.gremiumName ?? '');

  protected readonly confirmLabel = computed(
    () => this.transition()?.label || this.i18n.translate('applications.agenda.title'),
  );

  private seq = 0;

  constructor() {
    effect(() => {
      const open = this.open();
      const transition = this.transition();
      untracked(() => {
        if (open && transition) this.reset(transition);
      });
    });
  }

  close(): void {
    this.open.set(false);
  }

  private reset(transition: Transition): void {
    this.pick.set(null);
    this.nonPublic.set(false);
    this.note.set('');
    this.refusal.set(null);
    this.load(transition);
  }

  /** Load the planned meetings of the agenda gremium, oldest first. */
  private load(transition: Transition): void {
    const gremiumId = transition.agendaGremiumId;
    const seq = ++this.seq;
    this.meetings.set([]);
    if (!gremiumId) return;
    this.loading.set(true);
    this.api.listMeetings(gremiumId).subscribe({
      next: (list) => {
        if (seq !== this.seq) return;
        const planned = list
          .filter((m) => m.status === 'planned' && m.gremiumId === gremiumId)
          .sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
        this.meetings.set(planned);
        this.loading.set(false);
        const keep = planned.some((m) => m.id === this.pick());
        if (!keep) this.pick.set(this.suggestedId() ?? planned[0]?.id ?? null);
      },
      error: () => {
        if (seq !== this.seq) return;
        this.meetings.set([]);
        this.loading.set(false);
      },
    });
  }

  /** "Di, 18:00 · 7 TOPs". */
  private subLine(m: Meeting): string {
    const parts: string[] = [];
    const head: string[] = [];
    if (m.date) {
      const day = new Date(`${m.date}T00:00:00`);
      if (!Number.isNaN(day.getTime())) {
        head.push(
          day
            .toLocaleDateString(this.i18n.formatLocale(), { weekday: 'short' })
            .replace(/\.$/, ''),
        );
      }
    }
    if (m.startTime) head.push(m.startTime.slice(0, 5));
    if (head.length) parts.push(head.join(', '));
    const count = m.agendaItemCount ?? 0;
    parts.push(
      this.i18n.translate(
        count === 1 ? 'applications.agenda.itemsOne' : 'applications.agenda.itemsOther',
        { count },
      ),
    );
    return parts.join(' · ');
  }

  /** Fire the transition with the chosen meeting, or without one when none is visible. */
  submit(): void {
    const id = this.applicationId();
    const transition = this.transition();
    const meetingId = this.noMeeting() ? null : this.pick();
    if (!id || !transition || !this.canConfirm() || this.saving()) return;
    this.saving.set(true);
    this.refusal.set(null);
    const note = this.note().trim() || null;
    const body = meetingId
      ? { transitionId: transition.id, meetingId, nonPublic: this.nonPublic(), note }
      : { transitionId: transition.id, note };
    this.api
      .fireTransition(id, body)
      .subscribe({
        next: () => {
          this.saving.set(false);
          const meeting = this.meetings().find((m) => m.id === meetingId);
          this.toast.success(
            meeting
              ? this.i18n.translate('applications.agenda.added', { meeting: meeting.title })
              : this.i18n.translate('applications.actions.success'),
          );
          this.open.set(false);
          this.done.emit();
        },
        error: (err: { status?: number; error?: ProblemDetail | null }) => {
          this.saving.set(false);
          if (err.status === 422 && err.error?.code === 'agenda_meeting_invalid') {
            // The meeting started, closed or went away meanwhile: show it here and
            // offer the meetings that are still planned.
            this.refusal.set('applications.agenda.meetingInvalid');
            this.load(transition);
            return;
          }
          if (err.status === 409) {
            this.toast.error(this.i18n.translate('applications.actions.conflict'));
            this.open.set(false);
            this.done.emit();
            return;
          }
          this.toast.error(
            this.i18n.translate(
              err.status === 403 ? 'applications.transitions.forbidden' : 'applications.actions.error',
            ),
          );
        },
      });
  }
}

/** Date, then start time; a meeting without a date goes last. */
function sortKey(m: Meeting): string {
  return `${m.date ?? '9999-99-99'}T${m.startTime ?? '99:99'}`;
}
