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
import { Router } from '@angular/router';
import { forkJoin, of, type Observable } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type Delegation } from '@core/api/delegations.service';
import type { AgendaItem, Attendance, Meeting, Protocol } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { meetingStatus, type StatusView } from '@shared/status-kind.util';
import type { RowMenuItem, RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { RowMenuComponent } from '@shared/ui/row-menu/row-menu.component';
import type { Seg } from '@shared/ui/seg-bar/seg-bar.component';
import { SegBarComponent } from '@shared/ui/seg-bar/seg-bar.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { keeperNames } from '../keepers.util';
import { meetingTimeText, voteMetaLine, weekdayDate } from '../meetings-display.util';
import {
  type AgendaProgress,
  type AttendanceCounts,
  agendaProgress,
  attendanceCounts,
  openVoteOf,
  topsLabel,
} from '../meetings-overview.util';
import { SheetBarComponent } from '@shared/ui/sheet-bar/sheet-bar.component';

/** What the sheet loaded for the meeting. `null` = the request failed. */
interface SheetData {
  agenda: AgendaItem[] | null;
  attendance: Attendance[] | null;
  delegations: Delegation[] | null;
  protocol: Protocol | null;
}

/** One agenda row as the sheet shows it. */
interface AgendaRow {
  item: AgendaItem;
  number: number;
  title: string;
  /** "behandelt" (before the current item) or "Jetzt" (the current item). */
  mark: 'done' | 'now' | null;
}

/**
 * The detail sheet of one meeting in the list view of the overview (board Sitzungen,
 * variant A): what a reader needs to see whether the meeting is ready, without opening
 * it.
 *
 * Header: Gremium and date, the title, status · time · minute-taker (a warning while a
 * planned meeting has none), "Sitzung öffnen", "Beamer-Ansicht" (a live or planned
 * meeting, `canManage`, not on a phone) and "Protokollführung festlegen" (a planned
 * meeting without one). Edit and delete sit only here (`canManage`), not on the rows.
 *
 * Body: the agenda (done and current items marked, "nicht öffentlich"), the progress of a
 * live meeting and the turnout of its open vote, the attendance counts, the delegations
 * and the protocol state. The sheet reads the agenda, the roster, the delegations and the
 * protocol of the meeting with the existing endpoints, quietly, each time the meeting
 * changes. A part that does not load says so; the rest stays.
 */
@Component({
  selector: 'app-meeting-detail-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SheetBarComponent,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    RowMenuComponent,
    SegBarComponent,
    StatusTextComponent,
  ],
  templateUrl: './meeting-detail-sheet.component.html',
  styleUrl: './meeting-detail-sheet.component.scss',
})
export class MeetingDetailSheetComponent {
  private readonly api = inject(ApiClient);
  private readonly delegationsApi = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);

  readonly meeting = input.required<Meeting>();
  /** The sheet stands beside the list (surface 1, two columns). */
  readonly split = input(false);
  /** A phone viewport: the actions of the header go into the menu. */
  readonly phone = input(false);

  /** "Sitzung bearbeiten". */
  readonly edit = output<Meeting>();
  /** "Sitzung löschen". */
  readonly remove = output<Meeting>();
  /** "Beamer-Ansicht". */
  readonly beamer = output<Meeting>();

  readonly loading = signal(true);
  readonly data = signal<SheetData | null>(null);
  /** Load sequence: a late answer for a meeting that is no longer shown is dropped. */
  private seq = 0;

  readonly status = computed<StatusView>(() => meetingStatus(this.meeting().status));

  /** "Studierendenparlament · Di., 29.09.2026". */
  readonly metaLine = computed(() => {
    const m = this.meeting();
    const date = m.date ? weekdayDate(m.date, this.i18n.formatLocale()) : '';
    return [m.gremiumName, date].filter(Boolean).join(' · ');
  });

  /** "seit 18:04", "18:00–20:00" or "18:04–21:40". */
  readonly timeText = computed(() => {
    const t = meetingTimeText(this.meeting(), this.i18n.locale());
    if (!t.text) return '';
    return t.since ? this.i18n.translate('meetings.list.since', { time: t.text }) : t.text;
  });

  /** Every keeper of the minutes ("Mara Keller"), or '' without one. */
  readonly keepers = computed(() => keeperNames(this.meeting()));
  /** A planned meeting without a minute-taker cannot start: the sheet warns. */
  readonly keeperMissing = computed(
    () => this.meeting().status === 'planned' && !this.meeting().protokollantId,
  );

  /** The beamer needs `session.manage` and a meeting that is not closed. */
  readonly canBeamer = computed(
    () => this.meeting().canManage && this.meeting().status !== 'closed',
  );

  /** The progress of a live meeting, with the part of its bar. */
  readonly progress = computed<(AgendaProgress & { segs: Seg[] }) | null>(() => {
    const p = agendaProgress(this.meeting());
    return p && { ...p, segs: [{ value: p.position, tone: 'filled' }] };
  });

  /**
   * The open vote of a live meeting, with the part of its turnout bar, "TOP 3 · Einfache
   * Mehrheit" (the item and the majority) and its rules line for the tooltip.
   */
  readonly openVote = computed(() => {
    const v = this.meeting().status === 'live' ? openVoteOf(this.meeting()) : null;
    if (!v) return null;
    const parts: string[] = [];
    const index = this.agendaRows().findIndex((r) => r.item.id === v.agendaItemId);
    if (index >= 0) parts.push(this.i18n.translate('meetings.agenda.top', { n: index + 1 }));
    if (v.majorityRule) {
      parts.push(this.i18n.translate(`vote.majority.${v.majorityRule}` as TranslationKey));
    }
    return {
      ...v,
      segs: [{ value: v.voted, tone: 'filled' }] as Seg[],
      meta: parts.join(' · '),
      rules: voteMetaLine(v, (k, p) => this.i18n.translate(k, p), this.i18n.locale()),
    };
  });

  readonly agendaRows = computed<AgendaRow[]>(() => {
    const agenda = this.data()?.agenda ?? [];
    const m = this.meeting();
    const currentIndex = agenda.findIndex((a) => a.id === m.currentAgendaItemId);
    const marks = m.status === 'live' && currentIndex >= 0;
    return agenda.map((item, index) => ({
      item,
      number: index + 1,
      title: item.title?.trim() || this.i18n.translate('meetings.agenda.untitled'),
      mark: !marks ? null : index < currentIndex ? 'done' : index === currentIndex ? 'now' : null,
    }));
  });

  readonly counts = computed<AttendanceCounts | null>(() => {
    const rows = this.data()?.attendance;
    return rows ? attendanceCounts(rows) : null;
  });

  readonly delegations = computed(() => this.data()?.delegations ?? []);
  readonly protocol = computed(() => this.data()?.protocol ?? null);
  readonly protocolKey = computed<TranslationKey | null>(() => {
    const p = this.protocol();
    if (!p) return null;
    return p.status === 'final'
      ? 'meetings.protocol.final'
      : p.status === 'rendering'
        ? 'meetings.protocol.rendering'
        : 'meetings.protocol.draft';
  });

  /** The ⋮ menu of the header. On a phone it also holds the edit and the beamer. */
  readonly menu = computed<RowMenuSection[]>(() => {
    const m = this.meeting();
    if (!m.canManage) return [];
    const items: RowMenuItem[] = [];
    if (this.phone()) {
      items.push({ id: 'edit', label: this.i18n.translate('meetings.settings.title'), icon: 'edit' });
      if (this.canBeamer()) {
        items.push({ id: 'beamer', label: this.i18n.translate('meetings.beamer.enter'), icon: 'monitor' });
      }
    }
    items.push({
      id: 'delete',
      label: this.i18n.translate('meetings.delete.title'),
      icon: 'trash',
      danger: true,
    });
    return [{ items }];
  });

  constructor() {
    // Read the parts again when another meeting shows, not on each update of the same one.
    let shownId: string | null = null;
    effect(() => {
      const m = this.meeting();
      if (m.id === shownId) return;
      shownId = m.id;
      untracked(() => this.load(m));
    });
  }

  open(): void {
    void this.router.navigate(['/meetings', this.meeting().id]);
  }

  onMenu(item: RowMenuItem): void {
    const m = this.meeting();
    if (item.id === 'edit') this.edit.emit(m);
    else if (item.id === 'beamer') this.beamer.emit(m);
    else this.remove.emit(m);
  }

  /** "8 TOPs", "1 TOP" or "keine TOPs". */
  topsText(n: number): string {
    return topsLabel(n, (k, p) => this.i18n.translate(k, p));
  }

  /** "Anwesend 19 von 23" for the screen reader label of a bar. */
  turnoutLabel(voted: number, present: number): string {
    return this.i18n.translate('meetings.vote.progress', { voted, present });
  }

  private load(m: Meeting): void {
    const seq = ++this.seq;
    this.loading.set(true);
    this.data.set(null);
    const quiet = <T>(req: Observable<T>): Observable<T | null> =>
      req.pipe(catchError(() => of(null)));
    forkJoin({
      agenda: quiet(this.api.listAgenda(m.id, { quiet: true })),
      attendance: quiet(this.api.listAttendance(m.id, { quiet: true })),
      delegations: quiet(this.delegationsApi.list(m.id)),
      protocol: m.protocolId ? quiet(this.api.getProtocol(m.id, { quiet: true })) : of(null),
    }).subscribe((data) => {
      if (seq !== this.seq) return;
      this.data.set(data);
      this.loading.set(false);
    });
  }
}
