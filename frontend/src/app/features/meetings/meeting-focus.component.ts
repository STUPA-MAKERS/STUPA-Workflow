import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  model,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  AgendaItem,
  Attendance,
  AttendanceStatus,
  I18nMap,
  Meeting,
  MeetingVote,
  Protocol,
  Uuid,
} from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  CheckboxComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { MarkdownEditorComponent } from '@stupa-makers/ui-kit/markdown-editor';
import { MeetingAttendanceTableComponent } from './meeting-attendance-table.component';
import { MeetingDelegationCardComponent } from './meeting-delegation-card.component';
import { voteSnippet } from './meetings.util';
import {
  countEntries,
  meetingStatusKey,
  meetingStatusVariant,
  meetingTimeSuffix,
  resolveI18n,
  voteOptionLabel,
  voteOptionsFor,
  voteResultKey,
  voteResultVariant,
  voteStatusKey,
  voteStatusVariant,
} from './meetings-display.util';

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';
/** The popover that is open above the dock. */
export type DockPanel = 'none' | 'agenda' | 'attendance';

/**
 * The session page of the protokollant and the session lead.
 *
 * The page is the editor of the current agenda item. One bar at the top carries the
 * way back and the session controls. One dock at the bottom carries everything
 * that changes during the session: the current item, the vote, the ballot and the
 * room state. The agenda and the attendance open as popovers out of the dock.
 */
@Component({
  selector: 'app-meeting-focus',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    BadgeComponent,
    ButtonComponent,
    CheckboxComponent,
    IconComponent,
    SelectComponent,
    MarkdownEditorComponent,
    MeetingAttendanceTableComponent,
    MeetingDelegationCardComponent,
  ],
  templateUrl: './meeting-focus.component.html',
  styleUrl: './meeting-focus.component.scss',
  host: { '(document:keydown.escape)': 'closePanel()' },
})
export class MeetingFocusComponent {
  private readonly i18n = inject(I18nService);

  readonly meeting = input.required<Meeting>();
  readonly protocol = input.required<Protocol | null>();
  readonly agenda = input.required<AgendaItem[]>();
  /** The agenda item open in the editor, plus its 0-based index. */
  readonly top = input.required<AgendaItem | null>();
  readonly topIndex = input.required<number>();
  /**
   * Write the minutes. Once a protokollant is named only that person edits the
   * text. Everybody else with `canWrite` reads the page.
   */
  readonly canEdit = input.required<boolean>();
  readonly saveState = input.required<SaveState>();
  readonly attendance = input.required<Attendance[]>();
  readonly savingAttendance = input.required<boolean>();
  readonly viewers = input.required<string[]>();
  readonly casting = input.required<Uuid | null>();
  readonly deletingVote = input.required<Uuid | null>();
  readonly deletingProtocol = input.required<boolean>();
  readonly finalizing = input.required<boolean>();
  /** Own choice per vote id. It highlights the picked option. */
  readonly choices = input.required<Record<string, string>>();
  readonly assignableOptions = input.required<SelectOption[]>();
  readonly savingAgenda = input.required<boolean>();
  readonly renamingTopId = input.required<Uuid | null>();
  readonly agendaPick = model<string>('');
  readonly agendaFreetext = model<string>('');
  readonly renameDraft = model<string>('');

  /** Leave the session page for the meeting list. */
  readonly back = output<void>();
  readonly selectTop = output<Uuid>();
  readonly bodyChange = output<{ itemId: Uuid; body: string }>();
  readonly castVote = output<{ voteId: Uuid; choice: string }>();
  readonly voteClose = output<Uuid>();
  readonly voteCancel = output<Uuid>();
  readonly voteDelete = output<Uuid>();
  readonly voteDialog = output<AgendaItem>();
  readonly protocolDelete = output<void>();
  readonly startSession = output<void>();
  readonly closeSession = output<void>();
  readonly finalize = output<void>();
  readonly openSettings = output<void>();
  readonly deleteMeeting = output<void>();
  readonly toggleBeamer = output<void>();
  readonly attendanceChange = output<{ member: Attendance; status: AttendanceStatus }>();
  readonly addToAgenda = output<void>();
  readonly addFreetext = output<void>();
  readonly removeFromAgenda = output<Uuid>();
  readonly startRename = output<AgendaItem>();
  readonly cancelRename = output<void>();
  readonly renameTop = output<AgendaItem>();
  readonly setNonPublic = output<{ item: AgendaItem; nonPublic: boolean }>();
  readonly dragStart = output<number>();
  readonly dragOver = output<DragEvent>();
  readonly drop = output<number>();

  readonly panel = signal<DockPanel>('none');
  /**
   * The editor reloads its content only when the document key changes. An insert
   * from outside the editor, like a vote result, bumps this revision so the new
   * text shows up.
   */
  private readonly editorRev = signal(0);
  protected readonly docKey = computed(() => `${this.top()?.id ?? ''}:${this.editorRev()}`);

  protected readonly locked = computed(() => this.protocol()?.isLocked ?? false);
  protected readonly editable = computed(
    () => this.protocol() !== null && !this.locked() && this.canEdit(),
  );
  protected readonly canEditAgenda = computed(() => this.meeting().canWrite && !this.locked());

  protected readonly votes = computed<MeetingVote[]>(() => {
    const t = this.top();
    return t ? this.meeting().votes.filter((v) => v.agendaItemId === t.id) : [];
  });
  protected readonly openVote = computed(
    () => this.votes().find((v) => v.status === 'open') ?? null,
  );
  /** Every vote of the item that no longer runs: closed, cancelled or never opened. */
  protected readonly doneVotes = computed(() => this.votes().filter((v) => v.status !== 'open'));
  /** The last closed vote whose result is not in the text yet. */
  protected readonly pendingResult = computed<MeetingVote | null>(() => {
    if (this.openVote()) return null;
    const body = this.top()?.body ?? '';
    return (
      [...this.votes()]
        .reverse()
        .find((v) => v.status === 'closed' && !body.includes(`:::vote{#${v.id}}`)) ?? null
    );
  });

  /** The agenda item the room handles now, when it exists on the agenda. */
  protected readonly nowTop = computed<AgendaItem | null>(() => {
    const id = this.meeting().currentAgendaItemId;
    return id ? (this.agenda().find((a) => a.id === id) ?? null) : null;
  });
  protected readonly nowIndex = computed(() =>
    this.agenda().findIndex((a) => a.id === this.meeting().currentAgendaItemId),
  );
  /** The open item is not the one the room handles: somebody else moved "now". */
  protected readonly nowDiffers = computed(() => {
    const now = this.nowTop();
    const t = this.top();
    return now !== null && t !== null && now.id !== t.id;
  });
  protected readonly nowLabel = computed(() => {
    const now = this.nowTop();
    if (!now) return '';
    const n = this.nowIndex() + 1;
    const title = now.title || this.i18n.translate('meetings.agenda.untitled');
    return `${this.i18n.translate('meetings.agenda.top', { n })} · ${title}`;
  });

  protected readonly presentCount = computed(
    () => this.attendance().filter((a) => a.status === 'present').length,
  );
  protected readonly wordCount = computed(() => {
    const body = this.top()?.body?.trim() ?? '';
    return body ? body.split(/\s+/).length : 0;
  });
  protected readonly hasPrev = computed(() => this.topIndex() > 0);
  protected readonly hasNext = computed(
    () => this.topIndex() >= 0 && this.topIndex() < this.agenda().length - 1,
  );

  protected readonly statusVariant = meetingStatusVariant;
  protected readonly statusKey = meetingStatusKey;
  protected readonly timeSuffix = meetingTimeSuffix;
  protected readonly voteVariant = voteStatusVariant;
  protected readonly voteStatusKey = voteStatusKey;
  protected readonly voteResultKey = voteResultKey;
  protected readonly voteResultVariant = voteResultVariant;
  protected readonly countEntries = countEntries;
  protected readonly voteOptionsFor = voteOptionsFor;

  togglePanel(panel: Exclude<DockPanel, 'none'>): void {
    this.panel.set(this.panel() === panel ? 'none' : panel);
  }

  closePanel(): void {
    this.panel.set('none');
  }

  /** Move to the previous (-1) or the next (+1) agenda item. */
  step(delta: -1 | 1): void {
    const next = this.agenda()[this.topIndex() + delta];
    if (next) this.jump(next.id);
  }

  jump(id: Uuid): void {
    this.panel.set('none');
    this.selectTop.emit(id);
  }

  /** Append the result of a closed vote to the text of the open item. */
  insertResult(vote: MeetingVote): void {
    const t = this.top();
    if (!t) return;
    const body = (t.body ?? '').replace(/\s+$/, '');
    const snippet = voteSnippet(vote).replace(/^\n+/, '');
    this.bodyChange.emit({ itemId: t.id, body: body ? `${body}\n\n${snippet}` : snippet });
    this.editorRev.update((r) => r + 1);
  }

  /** An application item holds exactly one vote. A free-text item holds any number. */
  protected canAddVote(item: AgendaItem): boolean {
    return !item.applicationId || this.votesFor(item.id).length === 0;
  }

  protected votesFor(topId: Uuid): MeetingVote[] {
    return this.meeting().votes.filter((v) => v.agendaItemId === topId);
  }

  /** An item before "now" in the agenda order counts as handled. */
  protected isDone(index: number): boolean {
    const now = this.nowIndex();
    return now > -1 && index < now;
  }

  protected progress(vote: MeetingVote): number {
    return vote.present > 0 ? Math.min(100, Math.round((vote.voted / vote.present) * 100)) : 0;
  }

  protected myChoice(voteId: Uuid): string | null {
    return this.choices()[voteId] ?? null;
  }

  protected optionLabel(opt: string): string {
    return voteOptionLabel(opt, (key) => this.i18n.translate(key));
  }

  protected stateLabelOf(map: I18nMap | null | undefined): string {
    return resolveI18n(map, this.i18n.locale());
  }
}
