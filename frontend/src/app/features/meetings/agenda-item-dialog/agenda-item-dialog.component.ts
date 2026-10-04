import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { AgendaItem, AssignableApplication, Meeting, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SegmentedComponent,
  SwitchComponent,
  ToastService,
  type SegmentedOption,
} from '@stupa-makers/ui-kit';
import { errorDetail, resolveI18n } from '../meetings-display.util';

/** What the new agenda item is: an application of the Gremium, or a free text. */
export type AgendaItemKind = 'application' | 'freetext';

/**
 * "TOP hinzufügen": put an application on the agenda or add a free-text item.
 *
 * The application list is `GET …/agenda/assignable`: the applications of the meeting
 * Gremium in a vote state that are not on an agenda yet. The new item goes to the end
 * of the agenda. "Nicht öffentlich" marks it at once, so the public protocol leaves it
 * out.
 */
@Component({
  selector: 'app-agenda-item-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    DialogComponent,
    ButtonComponent,
    IconComponent,
    InputComponent,
    SegmentedComponent,
    SwitchComponent,
    SearchPillComponent,
    SkeletonComponent,
    StatusTextComponent,
  ],
  templateUrl: './agenda-item-dialog.component.html',
  styleUrl: './agenda-item-dialog.component.scss',
})
export class AgendaItemDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input(false);
  readonly meeting = input.required<Meeting>();
  /** The number that the new item gets: one after the last item. */
  readonly nextNumber = input(1);
  readonly closed = output<void>();
  /** The server added the item. Carries the new agenda. */
  readonly added = output<AgendaItem[]>();

  readonly kind = signal<AgendaItemKind>('application');
  readonly assignable = signal<AssignableApplication[]>([]);
  readonly loading = signal(false);
  readonly query = signal('');
  readonly pick = signal<Uuid | null>(null);
  readonly freetext = signal('');
  readonly nonPublic = signal(false);
  readonly saving = signal(false);

  readonly kindOptions = computed<SegmentedOption[]>(() => [
    { value: 'application', label: this.i18n.translate('meetings.agenda.assignHeading') },
    { value: 'freetext', label: this.i18n.translate('meetings.agenda.freetextHeading') },
  ]);

  /** The applications whose title holds the search text. */
  readonly shown = computed<AssignableApplication[]>(() => {
    const needle = this.query().trim().toLocaleLowerCase();
    const rows = this.assignable();
    return needle ? rows.filter((a) => (a.title ?? '').toLocaleLowerCase().includes(needle)) : rows;
  });

  readonly valid = computed(() =>
    this.kind() === 'application' ? this.pick() !== null : !!this.freetext().trim(),
  );

  constructor() {
    effect(() => {
      if (this.open()) untracked(() => this.reset());
    });
  }

  private reset(): void {
    this.kind.set('application');
    this.query.set('');
    this.pick.set(null);
    this.freetext.set('');
    this.nonPublic.set(false);
    this.saving.set(false);
    this.assignable.set([]);
    this.loading.set(true);
    this.api.listAssignableApplications(this.meeting().id).subscribe({
      next: (rows) => {
        this.loading.set(false);
        this.assignable.set(rows);
      },
      error: () => {
        this.loading.set(false);
        this.assignable.set([]);
      },
    });
  }

  setKind(value: string | null): void {
    if (value === 'application' || value === 'freetext') this.kind.set(value);
  }

  stateOf(a: AssignableApplication): string {
    return resolveI18n(a.stateLabel, this.i18n.locale());
  }

  cancel(): void {
    this.closed.emit();
  }

  submit(): void {
    if (!this.valid() || this.saving()) return;
    const meetingId = this.meeting().id;
    const pick = this.pick();
    const req =
      this.kind() === 'application' && pick !== null
        ? this.api.addAgendaItem(meetingId, pick, this.nonPublic())
        : this.api.addAgendaFreetext(meetingId, this.freetext().trim(), this.nonPublic());
    this.saving.set(true);
    req.subscribe({
      next: (rows) => {
        this.saving.set(false);
        this.added.emit(rows);
      },
      error: (err: unknown) => {
        this.saving.set(false);
        // A closed meeting answers 409 `meeting_closed`. Show the server reason.
        const detail = errorDetail(err);
        const base = this.i18n.translate('meetings.toast.actionFailed');
        this.toast.error(detail ? `${base}: ${detail}` : base);
      },
    });
  }
}
