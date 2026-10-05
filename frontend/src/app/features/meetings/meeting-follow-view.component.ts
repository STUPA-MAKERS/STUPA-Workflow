import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import type { MeetingDelegationContext } from '@core/api/delegations.service';
import type { AgendaItem, Attendance, Meeting, MeetingVote, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type StatusKind, type StatusView, meetingStatus } from '@shared/status-kind.util';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../layout/media-query';
import { AgendaPaneComponent } from './agenda-pane/agenda-pane.component';
import { MeetingDelegationCardComponent } from './meeting-delegation-card.component';
import {
  clockTime,
  meetingLine,
  shortTime,
  voteOptionLabel,
  weekdayDate,
} from './meetings-display.util';
import {
  type OwnAttendanceChange,
  ParticipantAttendanceComponent,
} from './participant-attendance/participant-attendance.component';
import { ParticipantVoteComponent } from './participant-vote/participant-vote.component';
import { ParticipantVoteService } from './participant-vote/participant-vote.service';
import { TopSheetComponent } from './top-sheet/top-sheet.component';

/** The length of the protocol excerpt on a phone, in characters. */
const EXCERPT_LENGTH = 160;

/**
 * The participant view of a meeting: the page of a member who neither leads the meeting
 * nor keeps the minutes (boards Teilnahme-Vorher, Teilnahme-Vertretung, Teilnahme-Live,
 * Teilnahme-Telefon, Schmal-Teilnahme).
 *
 * - Planned: the agenda (read only), "Die Sitzung beginnt am Di., 13.10.2026 um 18:00"
 *   with "Kalender abonnieren", and beside it "Deine Anwesenheit" (Anwesend or Abwesend,
 *   the reason, O15 lock) and "Vertretung" (the setup with its deadline).
 * - Live: the agenda with "Jetzt", the text of the item that the room handles ("Mara
 *   Keller führt das Protokoll"), the vote card with the two-step ballot (own row and the
 *   row of a represented member) and the delegation. The dock below: the item, the own
 *   ballot, the represented ballot and the attendance (it opens a sheet).
 * - Closed: the agenda, the texts and the results, the attendance as text.
 *
 * The view follows the room: until the member opens another item, the sheet shows the
 * item that the room handles. Below the wide layout the agenda opens as a sheet; on a
 * phone the page shows the item, the vote card, a protocol excerpt with "Ganzen TOP
 * lesen", then the attendance and the delegation.
 */
@Component({
  selector: 'app-meeting-follow-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [ParticipantVoteService],
  imports: [
    NgTemplateOutlet,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    StatusTextComponent,
    SideSheetComponent,
    AgendaPaneComponent,
    TopSheetComponent,
    ParticipantAttendanceComponent,
    ParticipantVoteComponent,
    MeetingDelegationCardComponent,
  ],
  templateUrl: './meeting-follow-view.component.html',
  styleUrl: './meeting-follow-view.component.scss',
})
export class MeetingFollowViewComponent {
  private readonly i18n = inject(I18nService);
  protected readonly votes = inject(ParticipantVoteService);

  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  readonly attendance = input.required<Attendance[]>();
  readonly savingAttendance = input(false);

  readonly back = output<void>();
  /** An own attendance report (Z2, O15). */
  readonly attendanceChange = output<{ member: Attendance } & OwnAttendanceChange>();

  protected readonly phone = mediaQuerySignal(MEDIA.phone);
  protected readonly wide = mediaQuerySignal(MEDIA.wide);

  /** The item the member opened. `null`: follow the room. */
  protected readonly selectedId = signal<Uuid | null>(null);
  protected readonly agendaOpen = signal(false);
  protected readonly attendanceOpen = signal(false);
  /** The phone shows the whole text of the item instead of the excerpt. */
  protected readonly fullText = signal(false);
  /** The delegation context of the meeting, as the delegation card loaded it. */
  protected readonly delegationContext = signal<MeetingDelegationContext | null>(null);

  constructor() {
    effect(() => this.votes.meeting.set(this.meeting()));
    effect(() => this.votes.row.set(this.voteRow()));
  }

  protected readonly status = computed<StatusView>(() => meetingStatus(this.meeting().status));

  /** The index of the item that the room handles now (live meeting only), or -1. */
  private readonly nowIndex = computed(() => {
    const m = this.meeting();
    if (m.status !== 'live' || !m.currentAgendaItemId) return -1;
    return this.agenda().findIndex((a) => a.id === m.currentAgendaItemId);
  });

  /**
   * The item in the sheet: the opened one, else the one that the room handles, else
   * (closed meeting) the last item of the room or the first one. A planned meeting
   * shows the start until the member opens an item.
   */
  protected readonly shownIndex = computed(() => {
    const id = this.selectedId();
    if (id) {
      const index = this.agenda().findIndex((a) => a.id === id);
      if (index >= 0) return index;
    }
    const m = this.meeting();
    if (m.status === 'live') return this.nowIndex();
    if (m.status === 'planned' || !this.agenda().length) return -1;
    // A closed meeting opens on its last item, else on the first one.
    return Math.max(0, this.agenda().findIndex((a) => a.id === m.currentAgendaItemId));
  });
  protected readonly shownTop = computed<AgendaItem | null>(
    () => this.agenda()[this.shownIndex()] ?? null,
  );

  /** The sheet shows the item that the room handles now. */
  protected readonly showsNow = computed(
    () => this.nowIndex() >= 0 && this.nowIndex() === this.shownIndex(),
  );

  /** "Jetzt läuft TOP 3 · …" while the member reads another item. */
  protected readonly nowElsewhere = computed<string | null>(() => {
    const now = this.nowIndex();
    if (now < 0 || now === this.shownIndex()) return null;
    const title = this.agenda()[now].title || this.i18n.translate('meetings.agenda.untitled');
    return `${this.i18n.translate('meetings.agenda.top', { n: now + 1 })} · ${title}`;
  });

  /** The vote of the card: the open vote, else the newest result of the shown item. */
  protected readonly voteRow = computed<MeetingVote | null>(() => {
    const votes = this.meeting().votes;
    const open = votes.find((v) => v.status === 'open');
    if (open) return open;
    const top = this.shownTop();
    if (!top) return null;
    const closed = votes.filter((v) => v.status === 'closed' && v.agendaItemId === top.id);
    return closed.length ? closed[closed.length - 1] : null;
  });

  /** The own row of the roster, or `null` (an external substitute has none). */
  protected readonly me = computed(() => this.attendance().find((a) => a.isSelf) ?? null);

  /** O23: the member handed this meeting to a substitute. */
  protected readonly delegated = computed(() => !!this.delegationContext()?.myDelegation);

  /** "Studierendenparlament · Di., 29.09.2026 · seit 18:04". */
  protected readonly subLine = computed(() => {
    const m = this.meeting();
    const locale = this.i18n.locale();
    const parts: string[] = [];
    if (m.gremiumName) parts.push(m.gremiumName);
    if (m.date) parts.push(this.dateText(m.date));
    const started = clockTime(m.startedAt, locale);
    if (m.status === 'live' && started) {
      parts.push(this.i18n.translate('meetings.page.since', { time: started }));
    } else if (m.status === 'closed' && started) {
      const closed = clockTime(m.closedAt, locale);
      parts.push(closed ? `${started}–${closed}` : started);
    } else if (m.startTime) {
      parts.push(shortTime(m.startTime));
    }
    return parts.join(' · ');
  });

  /** The phone keeps the time alone below the title: "seit 18:04". */
  protected readonly phoneSubLine = computed(() => {
    const m = this.meeting();
    const started = clockTime(m.startedAt, this.i18n.locale());
    if (m.status === 'live' && started) {
      return this.i18n.translate('meetings.page.since', { time: started });
    }
    return this.subLine();
  });

  /** "Die Sitzung beginnt am Di., 13.10.2026 um 18:00". */
  protected readonly startText = computed(() => {
    const m = this.meeting();
    if (!m.date) return this.i18n.translate('participant.start.noDate');
    const date = this.dateText(m.date);
    const time = shortTime(m.startTime);
    return time
      ? this.i18n.translate('participant.start.at', { date, time })
      : this.i18n.translate('participant.start.on', { date });
  });

  /** The line below the title of the delegation dialog: the meeting and its date. */
  protected readonly dialogLine = computed(() =>
    meetingLine(this.meeting(), this.i18n.formatLocale()),
  );

  /** "TOP 3 von 8". */
  protected readonly positionText = computed(() =>
    this.i18n.translate('participant.position', {
      n: this.shownIndex() + 1,
      m: this.agenda().length,
    }),
  );

  /** "Geschlossen um 21:12". */
  protected readonly closedLine = computed(() => {
    const time = clockTime(this.meeting().closedAt, this.i18n.locale());
    return time
      ? this.i18n.translate('meetings.dock.closedAt', { time })
      : this.i18n.translate('meetings.status.closed');
  });

  /** The own ballot of the open vote for the dock: "Deine Stimme: Ja" or "offen". */
  protected readonly ownBallot = computed<{ kind: StatusKind; text: string } | null>(() => {
    const vote = this.votes.vote();
    const own = this.votes.own();
    if (vote?.status !== 'open' || !own) return null;
    if (!own.cast) return { kind: 'warn', text: this.i18n.translate('participant.dock.open') };
    return {
      kind: 'accent',
      text: own.choice
        ? voteOptionLabel(own.choice, (key) => this.i18n.translate(key))
        : this.i18n.translate('meetings.dock.voteCast'),
    };
  });

  /** The represented ballot for the dock: "Vertretung: noch offen" or "abgegeben". */
  protected readonly proxyBallot = computed<{ kind: StatusKind; key: TranslationKey } | null>(() => {
    const vote = this.votes.vote();
    if (vote?.status !== 'open' || !this.votes.proxyName()) return null;
    return this.votes.proxyCast()
      ? { kind: 'accent', key: 'participant.dock.proxyCast' }
      : { kind: 'warn', key: 'participant.dock.proxyOpen' };
  });

  /** The own attendance as the dock chip shows it. */
  protected readonly attendanceChip = computed<TranslationKey>(() => {
    const status = this.me()?.status;
    if (status === 'present') return 'meetings.attendance.selfPresent';
    return status ? 'meetings.attendance.selfExcused' : 'meetings.attendance.unknown';
  });

  /** The text of the shown item as plain text, cut for the phone. */
  protected readonly excerpt = computed(() => {
    const plain = plainText(this.shownTop()?.body ?? '');
    if (plain.length <= EXCERPT_LENGTH) return { text: plain, cut: false };
    const cut = plain.slice(0, EXCERPT_LENGTH);
    const space = cut.lastIndexOf(' ');
    return { text: `${(space > 40 ? cut.slice(0, space) : cut).trimEnd()} …`, cut: true };
  });

  /** "Protokoll · Mara Keller schreibt mit". */
  protected readonly excerptCap = computed(() => {
    const m = this.meeting();
    return m.status === 'live' && m.protokollantName
      ? this.i18n.translate('participant.top.writing', { name: m.protokollantName })
      : this.i18n.translate('participant.top.protocol');
  });

  /** Open an item. The item of the room means: follow the room again. */
  protected pick(id: Uuid): void {
    const m = this.meeting();
    this.agendaOpen.set(false);
    this.fullText.set(false);
    if (m.status === 'planned' && this.selectedId() === id) {
      this.selectedId.set(null);
      return;
    }
    this.selectedId.set(m.status === 'live' && id === m.currentAgendaItemId ? null : id);
  }

  protected backToNow(): void {
    this.selectedId.set(null);
    this.fullText.set(false);
  }

  protected reportAttendance(change: OwnAttendanceChange): void {
    const member = this.me();
    if (member) this.attendanceChange.emit({ member, ...change });
  }

  private dateText(isoDate: string): string {
    return weekdayDate(isoDate, this.i18n.formatLocale());
  }
}

/** Markdown as plain text: no marks, no directives, one line. */
export function plainText(markdown: string): string {
  return markdown
    .replace(/^:::.*$/gm, ' ')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, '')
    .replace(/[*_`~]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}
