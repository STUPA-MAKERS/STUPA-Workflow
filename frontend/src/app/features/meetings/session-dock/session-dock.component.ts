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
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  AgendaItem,
  Attendance,
  AttendanceStatus,
  HandoverMode,
  Meeting,
  Uuid,
} from '@core/api/models';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import {
  type AttendanceChange,
  MeetingAttendanceTableComponent,
} from '../meeting-attendance-table.component';
import { MeetingDelegationCardComponent } from '../meeting-delegation-card.component';

/** The popover that is open above the dock. */
export type DockPanel = 'none' | 'attendance' | 'protokollant';

/**
 * The dock at the foot of the session page.
 *
 * Planned: "Noch nicht eröffnet · n TOPs vorbereitet", the minute-taker (marked while it
 * is missing; the meeting lead picks one here) and the attendance.
 *
 * Live and closed: the step through the agenda ("TOP 3 von 8"), the own ballot of the
 * open vote, or the way back to the item that runs now; the attendance, the minute-taker
 * ("Protokoll: Mara Keller", the handover for the lead and the minute-taker, Z3) and the
 * word count of the open item.
 *
 * The attendance and the minute-taker open as popovers above the dock. On a phone the
 * dock sits on the viewport above the navigation bar.
 */
@Component({
  selector: 'app-session-dock',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    AvatarComponent,
    MeetingAttendanceTableComponent,
    MeetingDelegationCardComponent,
  ],
  templateUrl: './session-dock.component.html',
  styleUrl: './session-dock.component.scss',
  host: {
    '(document:keydown.escape)': 'closePanel()',
  },
})
export class SessionDockComponent {
  private readonly i18n = inject(I18nService);

  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  /** The 0-based index of the item open in the sheet, or -1. */
  readonly topIndex = input.required<number>();
  readonly attendance = input.required<Attendance[]>();
  readonly savingAttendance = input(false);
  /** Names of the people who have the meeting open (WS presence). */
  readonly viewers = input<string[]>([]);
  readonly wordCount = input(0);
  /** The own ballot of the open vote ("Ja", "abgegeben"), or `null`. */
  readonly myVote = input<string | null>(null);
  readonly panel = model<DockPanel>('none');

  /** Move to the previous (-1) or the next (+1) agenda item. */
  readonly step = output<-1 | 1>();
  /** Open the item that the room handles now. */
  readonly jumpNow = output<Uuid>();
  readonly attendanceChange = output<AttendanceChange>();
  readonly attendanceReset = output<Attendance>();
  /** Name the minute-taker of a planned meeting. */
  readonly setProtokollant = output<Uuid>();
  /** Hand the minutes of a live meeting over, now or with the next item (Z3). */
  readonly handOver = output<{ principalId: Uuid; mode: HandoverMode }>();
  /** Discard the planned handover. */
  readonly cancelHandover = output<void>();

  /** The search text of the minute-taker picker. */
  protected readonly keeperQuery = signal('');
  /** When the minutes change hands in a live meeting: at once or with the next item. */
  protected readonly handoverMode = signal<HandoverMode>('now');

  protected readonly presentCount = computed(
    () => this.attendance().filter((a) => a.status === 'present').length,
  );
  protected readonly hasPrev = computed(() => this.topIndex() > 0);
  protected readonly hasNext = computed(
    () => this.topIndex() >= 0 && this.topIndex() < this.agenda().length - 1,
  );

  /** The index of the item that the room handles now, or -1. */
  private readonly nowIndex = computed(() =>
    this.agenda().findIndex((a) => a.id === this.meeting().currentAgendaItemId),
  );
  /** The item the room handles now with its label, when it is not the open one. */
  protected readonly nowElsewhere = computed<{ item: AgendaItem; label: string } | null>(() => {
    const now = this.nowIndex();
    if (now < 0 || this.topIndex() < 0 || now === this.topIndex()) return null;
    const item = this.agenda()[now];
    const title = item.title || this.i18n.translate('meetings.agenda.untitled');
    return { item, label: `${this.i18n.translate('meetings.agenda.top', { n: now + 1 })} · ${title}` };
  });

  /** The meeting lead names the minute-taker of a planned meeting. */
  protected readonly canPickKeeper = computed(() => {
    const m = this.meeting();
    return m.status === 'planned' && m.canManage;
  });
  /** The meeting lead and the minute-taker hand the minutes of a live meeting over. */
  protected readonly canHandOver = computed(() => {
    const m = this.meeting();
    return m.status === 'live' && (m.canManage || m.isProtokollant);
  });
  /** A handover with the next item needs an item after the current one. */
  protected readonly hasNextForHandover = computed(() => {
    const count = this.agenda().length;
    return count > 0 && this.nowIndex() < count - 1;
  });

  /**
   * The members who can keep the minutes and match the search. O20: only a member with
   * `protocol.write` qualifies; the server answers 422 for any other.
   */
  protected readonly keeperCandidates = computed(() => {
    const q = this.keeperQuery().trim().toLowerCase();
    return this.attendance().filter((a) => {
      if (!a.canKeepProtocol) return false;
      if (!q) return true;
      return [a.displayName, a.email].some((v) => v?.toLowerCase().includes(q));
    });
  });

  togglePanel(panel: Exclude<DockPanel, 'none'>): void {
    if (panel === 'protokollant') {
      this.keeperQuery.set('');
      this.handoverMode.set('now');
    }
    this.panel.set(this.panel() === panel ? 'none' : panel);
  }

  closePanel(): void {
    this.panel.set('none');
  }

  /**
   * Name a member as the minute-taker and close the picker. A planned meeting assigns
   * the person; a live meeting hands the minutes over in the chosen mode.
   */
  pickKeeper(principalId: Uuid): void {
    this.panel.set('none');
    const m = this.meeting();
    if (principalId === m.protokollantId) return;
    if (m.status === 'live') {
      const mode = this.hasNextForHandover() ? this.handoverMode() : 'now';
      this.handOver.emit({ principalId, mode });
      return;
    }
    this.setProtokollant.emit(principalId);
  }

  protected memberName(a: Attendance): string {
    return a.displayName || a.email || a.principalId;
  }

  protected attendanceKey(status: AttendanceStatus | null): TranslationKey {
    return status ? `meetings.attendance.${status}` : 'meetings.attendance.unknown';
  }
}
