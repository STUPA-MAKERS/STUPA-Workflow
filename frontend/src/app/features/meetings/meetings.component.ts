import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  AgendaItem,
  Attendance,
  AttendanceStatus,
  HandoverMode,
  Meeting,
  MeetingVote,
  Uuid,
} from '@core/api/models';
import type { BadgeVariant } from '@stupa-makers/ui-kit';
import {
  BadgeComponent,
  ButtonComponent,
  CardComponent,
  IconComponent,
} from '@stupa-makers/ui-kit';
import type { TranslationKey } from '@core/i18n/translations';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { AgendaItemDialogComponent } from './agenda-item-dialog/agenda-item-dialog.component';
import { CloseMeetingDialogComponent } from './close-meeting-dialog/close-meeting-dialog.component';
import { DeleteMeetingDialogComponent } from './delete-meeting-dialog/delete-meeting-dialog.component';
import { MeetingAgendaService } from './meeting-agenda.service';
import { MeetingBeamerComponent } from './meeting-beamer.component';
import { MeetingDialogsService } from './meeting-dialogs.service';
import { MeetingFollowViewComponent } from './meeting-follow-view.component';
import { MeetingPageComponent } from './meeting-page/meeting-page.component';
import { MeetingSessionService } from './meeting-session.service';
import { MeetingSettingsDialogComponent } from './meeting-settings-dialog/meeting-settings-dialog.component';
import { MeetingsListComponent } from './meetings-list/meetings-list.component';
import { MeetingsTimelineService } from './meetings-timeline.service';
import { VoteOpenDialogComponent } from './vote-open-dialog/vote-open-dialog.component';
import {
  countEntries,
  meetingStatusKey,
  meetingStatusVariant,
  meetingTimeSuffix,
  voteOptionLabel,
  voteOptionsFor,
  voteResultKey,
  voteResultVariant,
  voteStatusKey,
  voteStatusVariant,
} from './meetings-display.util';

/**
 * Meetings page: the list (`/meetings`, `MeetingsListComponent`) and the meeting
 * page (`/meetings/:id`). The meeting page is the session page for the minute-taker
 * and the lead, the follow view for a member, and the beamer. This component wires
 * the component-scoped services and the meeting dialogs; its public surface also
 * drives the specs.
 */
@Component({
  selector: 'app-meetings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [
    MeetingAgendaService,
    MeetingSessionService,
    MeetingsTimelineService,
    MeetingDialogsService,
  ],
  imports: [
    TranslatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    IconComponent,
    LocalizedDatePipe,
    PageHeaderComponent,
    MeetingBeamerComponent,
    MeetingPageComponent,
    MeetingFollowViewComponent,
    MeetingsListComponent,
    MeetingSettingsDialogComponent,
    DeleteMeetingDialogComponent,
    CloseMeetingDialogComponent,
    VoteOpenDialogComponent,
    AgendaItemDialogComponent,
  ],
  templateUrl: './meetings.component.html',
  styleUrl: './meetings.component.scss',
})
export class MeetingsComponent {
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly session = inject(MeetingSessionService);
  private readonly agendaSvc = inject(MeetingAgendaService);
  private readonly timeline = inject(MeetingsTimelineService);
  protected readonly dialogs = inject(MeetingDialogsService);

  /** Detail route (`/meetings/:id`) vs. list (`/meetings`). */
  readonly detailMode = signal(false);
  /** Beamer display (only current question + live result, no dialogs). */
  readonly beamerMode = signal(false);

  readonly loading = this.session.loading;
  readonly error = this.session.error;
  readonly meeting = this.session.meeting;
  readonly protocol = this.session.protocol;
  readonly attendance = this.session.attendance;
  readonly viewers = this.session.viewers;
  readonly savingAttendance = this.session.savingAttendance;
  readonly finalizing = this.session.finalizing;
  readonly casting = this.session.casting;
  readonly deletingVote = this.session.deletingVote;
  protected readonly myChoices = this.session.myChoices;
  readonly looseVotes = this.session.looseVotes;
  readonly beamerVote = this.session.beamerVote;
  readonly currentTop = this.session.currentTop;
  readonly currentTopIndex = this.session.currentTopIndex;

  readonly canManage = this.session.canManage;
  readonly canWrite = this.session.canWrite;
  readonly canManageVotes = this.session.canManageVotes;
  readonly canVote = this.session.canVote;
  readonly canViewAll = this.session.canViewAll;
  readonly isProtokollant = this.session.isProtokollant;
  readonly isFollower = this.session.isFollower;
  readonly canEditProtocol = this.session.canEditProtocol;
  /** May see the (server-side filtered) list. Same predicate as `loadList()`. */
  readonly showOverview = this.timeline.canReadTimeline;
  readonly showForbidden = computed(() => !this.detailMode() && !this.showOverview());

  readonly agenda = this.agendaSvc.agenda;
  readonly savingAgenda = this.agendaSvc.savingAgenda;
  readonly renamingTopId = this.agendaSvc.renamingTopId;
  readonly renameDraft = this.agendaSvc.renameDraft;
  readonly selectedTopId = this.agendaSvc.selectedTopId;
  readonly saveState = this.agendaSvc.saveState;
  readonly selectedTop = this.agendaSvc.selectedTop;
  readonly selectedIndex = this.agendaSvc.selectedIndex;

  /** The 1-based agenda number of the item that gets the vote. */
  readonly voteTopNumber = computed(() => {
    const it = this.dialogs.voteItem();
    return it ? this.agenda().findIndex((a) => a.id === it.id) + 1 : 0;
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      const id = pm.get('id');
      this.detailMode.set(!!id);
      if (id) {
        this.session.loadMeeting(id);
      } else {
        this.meeting.set(null);
        this.timeline.loadList();
      }
    });
  }

  /** Back from the meeting page to the list. */
  goBack(): void {
    void this.router.navigate(['/meetings']);
  }

  openSettings(m: Meeting): void {
    this.dialogs.openSettings(m);
  }

  askDeleteMeeting(m: Meeting): void {
    this.dialogs.askDeleteMeeting(m);
  }

  /** Name the minute-taker straight from the page of a planned meeting. */
  setProtokollant(m: Meeting, principalId: Uuid): void {
    this.dialogs.setProtokollant(m, principalId);
  }

  /**
   * Hand the minutes of a live meeting over (Z3). The open text of the item is saved
   * first, because the write right can move with the handover. The handover request
   * starts only after the response of that save.
   */
  handOver(m: Meeting, principalId: Uuid, mode: HandoverMode): void {
    this.agendaSvc
      .settlePendingBody(this.meeting()?.id ?? null)
      .subscribe(() => this.dialogs.handOver(m, principalId, mode));
  }

  /** Discard the planned handover. */
  cancelHandover(m: Meeting): void {
    this.dialogs.cancelHandover(m);
  }

  startMeeting(): void {
    this.session.startMeeting();
  }

  /** "Sitzung schließen": save the open text first, then ask. */
  askCloseMeeting(): void {
    this.flushPendingBody();
    this.dialogs.closeOpen.set(true);
  }

  setActive(applicationId: Uuid): void {
    this.session.setActive(applicationId);
  }

  openVote(voteId: Uuid): void {
    this.session.openVote(voteId);
  }

  closeVote(voteId: Uuid): void {
    this.session.closeVote(voteId);
  }

  cancelVote(voteId: Uuid): void {
    this.session.cancelVote(voteId);
  }

  cast(voteId: Uuid, choice: string): void {
    this.session.cast(voteId, choice);
  }

  deleteVote(voteId: Uuid): void {
    this.session.deleteVote(voteId);
  }

  myChoice(voteId: Uuid): string | null {
    return this.myChoices()[voteId] ?? null;
  }

  finalize(): void {
    this.session.finalize();
  }

  setAttendance(member: Attendance, status: AttendanceStatus, note?: string | null): void {
    this.session.setAttendance(member, status, note);
  }

  resetAttendance(member: Attendance): void {
    this.session.resetAttendance(member);
  }

  /** "Abstimmung öffnen" for an agenda item. */
  openVoteDialog(item: AgendaItem): void {
    this.dialogs.voteItem.set(item);
  }

  /** "TOP hinzufügen". */
  openAgendaDialog(): void {
    this.dialogs.agendaOpen.set(true);
  }

  /** The agenda dialog added an item: show the new agenda. */
  agendaAdded(rows: AgendaItem[]): void {
    this.agendaSvc.agenda.set(rows);
    this.dialogs.agendaOpen.set(false);
  }

  selectTop(id: Uuid): void {
    this.agendaSvc.selectTop(this.meeting()?.id ?? null, id);
  }

  /** Open a TOP and, for the room lead, make it the one the room handles now. */
  jumpTo(id: Uuid): void {
    this.selectTop(id);
    this.session.setCurrentTop(id);
  }

  onTopBodyChange(itemId: Uuid, body: string): void {
    const m = this.meeting();
    if (!m) return;
    this.agendaSvc.onTopBodyChange(m.id, itemId, body);
  }

  flushPendingBody(): void {
    this.agendaSvc.flushPendingBody(this.meeting()?.id ?? null);
  }

  onTopDragStart(index: number): void {
    this.agendaSvc.onTopDragStart(index);
  }

  onTopDragOver(event: DragEvent): void {
    this.agendaSvc.onTopDragOver(event);
  }

  onTopDrop(index: number): void {
    this.agendaSvc.onTopDrop(this.meeting()?.id ?? null, index);
  }

  /** "Nach oben" / "Nach unten" in the row menu of an agenda item. */
  moveTop(from: number, to: number): void {
    this.agendaSvc.moveTop(this.meeting()?.id ?? null, from, to);
  }

  removeFromAgenda(itemId: Uuid): void {
    const m = this.meeting();
    if (!m) return;
    this.agendaSvc.removeFromAgenda(m.id, itemId);
  }

  startRename(item: AgendaItem): void {
    this.agendaSvc.startRename(item);
  }

  cancelRename(): void {
    this.agendaSvc.cancelRename();
  }

  renameTop(item: AgendaItem): void {
    this.agendaSvc.renameTop(this.meeting()?.id ?? null, item);
  }

  setNonPublic(item: AgendaItem, nonPublic: boolean): void {
    const m = this.meeting();
    if (!m) return;
    this.agendaSvc.setNonPublic(m.id, item, nonPublic);
  }

  // The display helpers below are pure, see meetings-display.util.
  voteOptionLabel(opt: string): string {
    return voteOptionLabel(opt, (key) => this.i18n.translate(key));
  }

  /** `", 18:00"` behind the meeting date, or nothing. See meetings-display.util. */
  timeSuffix(startTime: string | null | undefined): string {
    return meetingTimeSuffix(startTime);
  }

  statusVariant(status: Meeting['status']): BadgeVariant {
    return meetingStatusVariant(status);
  }

  statusKey(status: Meeting['status']): TranslationKey {
    return meetingStatusKey(status);
  }

  voteVariant(status: MeetingVote['status']): BadgeVariant {
    return voteStatusVariant(status);
  }

  voteStatusKey(status: MeetingVote['status']): TranslationKey {
    return voteStatusKey(status);
  }

  voteResultKey(result: string | null | undefined): TranslationKey {
    return voteResultKey(result);
  }

  voteResultVariant(result: string | null | undefined): BadgeVariant {
    return voteResultVariant(result);
  }

  countEntries(vote: MeetingVote): { key: string; value: number }[] {
    return countEntries(vote);
  }

  voteOptionsFor(vote: MeetingVote): string[] {
    return voteOptionsFor(vote);
  }
}
