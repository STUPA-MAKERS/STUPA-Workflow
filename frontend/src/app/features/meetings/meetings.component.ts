import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  AgendaItem,
  Attendance,
  AttendanceStatus,
  I18nMap,
  Meeting,
  MeetingVote,
  Uuid,
} from '@core/api/models';
import type { BadgeVariant } from '@stupa-makers/ui-kit';
import {
  BadgeComponent,
  ButtonComponent,
  CardComponent,
  CheckboxComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  type IconName,
  SelectComponent,
  TimeInputComponent,
} from '@stupa-makers/ui-kit';
import type { TranslationKey } from '@core/i18n/translations';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { MeetingAgendaService } from './meeting-agenda.service';
import { MeetingBeamerComponent } from './meeting-beamer.component';
import { MeetingDialogsService } from './meeting-dialogs.service';
import { MeetingFocusComponent } from './meeting-focus.component';
import { MeetingFollowViewComponent } from './meeting-follow-view.component';
import { MeetingSessionService } from './meeting-session.service';
import { MeetingsTimelineService } from './meetings-timeline.service';
import { renderMarkdown } from './meetings.util';
import {
  FIXED_VOTE_OPTIONS,
  attendanceBadgeVariant,
  attendanceButtonVariant,
  attendanceIcon,
  attendanceKey,
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

/**
 * Meetings page: overview timeline (`/meetings`) and the session detail view
 * (`/meetings/:id`), which is the focus page for the protokollant, the follow
 * view for a member and the beamer. This component is a thin facade over the
 * component-scoped services below. Its public surface also drives the specs.
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
    FormsModule,
    TranslatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    CheckboxComponent,
    SelectComponent,
    DatepickerComponent,
    TimeInputComponent,
    DialogComponent,
    IconComponent,
    LocalizedDatePipe,
    PageHeaderComponent,
    MeetingBeamerComponent,
    MeetingFocusComponent,
    MeetingFollowViewComponent,
    NgTemplateOutlet,
  ],
  templateUrl: './meetings.component.html',
  styleUrl: './meetings.component.scss',
})
export class MeetingsComponent implements OnDestroy {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly session = inject(MeetingSessionService);
  private readonly agendaSvc = inject(MeetingAgendaService);
  private readonly timeline = inject(MeetingsTimelineService);
  private readonly dialogs = inject(MeetingDialogsService);

  /** Detail route (`/meetings/:id`) vs. overview (`/meetings`). */
  readonly detailMode = signal(false);
  /** Beamer display (only current question + live result, no dialogs). */
  readonly beamerMode = signal(false);
  /** Confirmation dialog for (irrevocably) closing the session. */
  readonly closeConfirmOpen = signal(false);

  readonly loading = this.session.loading;
  readonly error = this.session.error;
  readonly meeting = this.session.meeting;
  readonly protocol = this.session.protocol;
  readonly attendance = this.session.attendance;
  readonly viewers = this.session.viewers;
  readonly savingAttendance = this.session.savingAttendance;
  readonly planDate = this.session.planDate;
  readonly planTime = this.session.planTime;
  readonly savingDate = this.session.savingDate;
  readonly finalizing = this.session.finalizing;
  readonly casting = this.session.casting;
  readonly deletingVote = this.session.deletingVote;
  readonly confirmDeleteProtocol = this.session.confirmDeleteProtocol;
  readonly deletingProtocol = this.session.deletingProtocol;
  protected readonly myChoices = this.session.myChoices;
  readonly voteDialogOpen = this.session.voteDialogOpen;
  readonly voteQuestion = this.session.voteQuestion;
  readonly voteSecret = this.session.voteSecret;
  readonly voteMajorityRule = this.session.voteMajorityRule;
  readonly majorityRuleOptions = this.session.majorityRuleOptions;
  readonly openingVote = this.session.openingVote;
  readonly looseVotes = this.session.looseVotes;
  readonly beamerVote = this.session.beamerVote;
  readonly currentTop = this.session.currentTop;
  readonly currentTopIndex = this.session.currentTopIndex;
  readonly FIXED_VOTE_OPTIONS = FIXED_VOTE_OPTIONS;

  readonly canManageAny = this.session.canManageAny;
  readonly canManage = this.session.canManage;
  readonly canWrite = this.session.canWrite;
  readonly canManageVotes = this.session.canManageVotes;
  readonly canVote = this.session.canVote;
  readonly canViewAll = this.session.canViewAll;
  readonly isProtokollant = this.session.isProtokollant;
  readonly isFollower = this.session.isFollower;
  readonly canEditProtocol = this.session.canEditProtocol;
  /** Create needs global `meeting.manage` OR a manage role in at least one Gremium. */
  readonly canCreate = computed(
    () => this.canManageAny() || this.auth.sessionManageGremien().length > 0,
  );
  readonly canWriteGlobal = computed(() => this.auth.can('protocol.write'));
  readonly inAnyCommittee = computed(() => this.auth.gremien().length > 0);
  readonly inSubstitutePool = computed(() => this.auth.inSubstitutePool());
  /** May see the (server-side filtered) overview timeline. */
  readonly showOverview = computed(
    () =>
      this.canManageAny() ||
      this.canWriteGlobal() ||
      this.inAnyCommittee() ||
      this.inSubstitutePool(),
  );
  readonly showForbidden = computed(
    () =>
      !this.detailMode() &&
      !this.canManageAny() &&
      !this.canWriteGlobal() &&
      !this.inAnyCommittee() &&
      !this.inSubstitutePool(),
  );

  readonly agenda = this.agendaSvc.agenda;
  readonly assignable = this.agendaSvc.assignable;
  readonly savingAgenda = this.agendaSvc.savingAgenda;
  readonly agendaPick = this.agendaSvc.agendaPick;
  readonly agendaFreetext = this.agendaSvc.agendaFreetext;
  readonly renamingTopId = this.agendaSvc.renamingTopId;
  readonly renameDraft = this.agendaSvc.renameDraft;
  readonly selectedTopId = this.agendaSvc.selectedTopId;
  readonly savingTop = this.agendaSvc.savingTop;
  readonly saveState = this.agendaSvc.saveState;
  readonly selectedTop = this.agendaSvc.selectedTop;
  readonly selectedIndex = this.agendaSvc.selectedIndex;
  readonly assignableOptions = this.agendaSvc.assignableOptions;

  readonly loadingList = this.timeline.loadingList;

  /** Rows to outline while the timeline first loads, so the page keeps its shape. */
  protected readonly skeletonRows = [0, 1, 2, 3, 4];
  readonly upcomingItems = this.timeline.upcomingItems;
  readonly pastItems = this.timeline.pastItems;
  readonly upcomingHasMore = this.timeline.upcomingHasMore;
  readonly pastHasMore = this.timeline.pastHasMore;
  readonly loadingUpcoming = this.timeline.loadingUpcoming;
  readonly loadingPast = this.timeline.loadingPast;
  readonly gremiumFilter = this.timeline.gremiumFilter;
  readonly filterGremien = this.timeline.filterGremien;
  readonly filterGremiumOptions = this.timeline.filterGremiumOptions;
  readonly searchQuery = this.timeline.searchQuery;
  readonly searchActive = this.timeline.searchActive;
  readonly searchItems = this.timeline.searchItems;
  readonly searchHasMore = this.timeline.searchHasMore;
  readonly loadingSearch = this.timeline.loadingSearch;
  readonly hasMorePast = this.timeline.hasMorePast;
  readonly timelineEmpty = this.timeline.timelineEmpty;
  readonly searchEmpty = this.timeline.searchEmpty;

  readonly createOpen = this.dialogs.createOpen;
  readonly createStep = this.dialogs.createStep;
  readonly creating = this.dialogs.creating;
  readonly newTitle = this.dialogs.newTitle;
  readonly newDate = this.dialogs.newDate;
  readonly newTime = this.dialogs.newTime;
  readonly newEndTime = this.dialogs.newEndTime;
  readonly newGremiumId = this.dialogs.newGremiumId;
  readonly newProtokollant = this.dialogs.newProtokollant;
  readonly createMembers = this.dialogs.createMembers;
  readonly createProtokollantOptions = this.dialogs.createProtokollantOptions;
  readonly gremiumOptions = this.dialogs.gremiumOptions;
  readonly createStep1Valid = this.dialogs.createStep1Valid;
  readonly settingsMeeting = this.dialogs.settingsMeeting;
  readonly settingsRoster = this.dialogs.settingsRoster;
  readonly settingsProtokollant = this.dialogs.settingsProtokollant;
  readonly settingsDate = this.dialogs.settingsDate;
  readonly settingsTime = this.dialogs.settingsTime;
  readonly settingsEndTime = this.dialogs.settingsEndTime;
  readonly savingSettings = this.dialogs.savingSettings;
  readonly settingsLocked = this.dialogs.settingsLocked;
  readonly protokollantLocked = this.dialogs.protokollantLocked;
  readonly protokollantOptions = this.dialogs.protokollantOptions;
  readonly confirmDeleteMeeting = this.dialogs.confirmDeleteMeeting;
  readonly deletingMeeting = this.dialogs.deletingMeeting;

  readonly timelineScroll = viewChild<ElementRef<HTMLElement>>('tlScroll');
  readonly nowMarker = viewChild<ElementRef<HTMLElement>>('nowMarker');

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
    // Position the timeline once on the "now" marker as soon as the list is
    // loaded and rendered. Upcoming meetings stay visible. A scroll up reaches
    // the past ones.
    effect(() => {
      const marker = this.nowMarker()?.nativeElement;
      const scroller = this.timelineScroll()?.nativeElement;
      // Dependencies: reposition once both directions have arrived.
      this.pastItems();
      this.upcomingItems();
      if (marker && scroller && !this.timeline.didInitialScroll && !this.loadingList()) {
        this.timeline.didInitialScroll = true;
        // Double rAF: measure after layout. getBoundingClientRect works with
        // any offsetParent, offsetTop does not. Otherwise the list lands on the
        // oldest meeting instead of "now".
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const m = this.nowMarker()?.nativeElement;
            const s = this.timelineScroll()?.nativeElement;
            if (!m || !s) return;
            const top =
              m.getBoundingClientRect().top - s.getBoundingClientRect().top + s.scrollTop - 8;
            s.scrollTop = Math.max(0, top);
          });
        });
      }
    });
    // Size the timeline to the free viewport space whenever it appears or its
    // content grows. A separate resize listener handles window resizes.
    effect(() => {
      const el = this.timelineScroll();
      // Dependencies: appearance and content amount, including search hits.
      this.timelineEmpty();
      this.loadingList();
      this.pastItems();
      this.upcomingItems();
      this.searchItems();
      if (el) this.scheduleMeasure();
    });
    window.addEventListener('resize', this.onResize, { passive: true });
  }

  ngOnDestroy(): void {
    window.removeEventListener('resize', this.onResize);
    if (this.measureRaf !== null) cancelAnimationFrame(this.measureRaf);
  }

  /** Minimum timeline height (px) for very small viewports. */
  private readonly TIMELINE_MIN_PX = 192;
  private measureRaf: number | null = null;
  private readonly onResize = (): void => this.scheduleMeasure();

  /** Batch the measurement onto the next frame (layout must be settled). */
  private scheduleMeasure(): void {
    if (this.measureRaf !== null) cancelAnimationFrame(this.measureRaf);
    this.measureRaf = requestAnimationFrame(() => {
      this.measureRaf = null;
      this.measureTimeline();
    });
  }

  /**
   * Timeline height = viewport − everything above (header, breadcrumb, h1,
   * toolbar) − everything below (footer + bottom padding of main). The method
   * measures independent of the scroll position, because `rect.top + scrollY`
   * is the absolute layout offset. Only the timeline scrolls, never the page.
   */
  private measureTimeline(): void {
    const el = this.timelineScroll()?.nativeElement;
    if (!el) return;
    const topOffset = el.getBoundingClientRect().top + window.scrollY;
    const footer = document.querySelector<HTMLElement>('.footer');
    const footerH = footer ? footer.offsetHeight : 0;
    const main = el.closest<HTMLElement>('.main');
    const mainPadBottom = main
      ? Number.parseFloat(getComputedStyle(main).paddingBottom) || 0
      : 0;
    const avail = window.innerHeight - topOffset - footerH - mainPadBottom - 8;
    el.style.height = `${Math.max(this.TIMELINE_MIN_PX, Math.round(avail))}px`;
  }

  onTimelineScroll(el: HTMLElement): void {
    this.timeline.onScroll(el);
  }

  onSearch(value: string): void {
    this.timeline.onSearch(value);
  }

  loadMoreSearch(): void {
    this.timeline.loadMoreSearch();
  }

  selectGremiumFilter(id: string): void {
    this.timeline.selectGremiumFilter(id);
  }

  loadMorePast(el: HTMLElement): void {
    this.timeline.loadMorePast(el);
  }

  loadMoreUpcoming(): void {
    this.timeline.loadMoreUpcoming();
  }

  /** Open a meeting from the list → detail route. */
  openMeeting(id: Uuid): void {
    void this.router.navigate(['/meetings', id]);
  }

  /** Back from the session page to the meeting list. */
  goBack(): void {
    void this.router.navigate(['/meetings']);
  }

  openCreate(): void {
    this.dialogs.openCreate();
  }

  closeCreate(): void {
    this.dialogs.closeCreate();
  }

  goToCreateStep2(): void {
    this.dialogs.goToCreateStep2();
  }

  backToCreateStep1(): void {
    this.dialogs.backToCreateStep1();
  }

  onCreateGremiumChange(gremiumId: string): void {
    this.dialogs.onCreateGremiumChange(gremiumId);
  }

  create(event: Event): void {
    event.preventDefault();
    this.dialogs.create();
  }

  openSettings(m: Meeting): void {
    this.dialogs.openSettings(m);
  }

  closeSettings(): void {
    this.dialogs.closeSettings();
  }

  saveSettings(): void {
    this.dialogs.saveSettings();
  }

  askDeleteMeeting(m: Meeting): void {
    this.dialogs.askDeleteMeeting(m);
  }

  doDeleteMeeting(): void {
    this.dialogs.doDeleteMeeting();
  }

  setStatus(status: 'live' | 'closed'): void {
    this.session.setStatus(status);
  }

  closeMeeting(): void {
    this.session.closeMeeting();
  }

  savePlannedDate(): void {
    this.session.savePlannedDate();
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

  votesForTop(topId: Uuid): MeetingVote[] {
    return this.session.votesForTop(topId);
  }

  finalize(): void {
    this.session.finalize();
  }

  askDeleteProtocol(): void {
    this.session.askDeleteProtocol();
  }

  closeDeleteProtocol(): void {
    this.session.closeDeleteProtocol();
  }

  doDeleteProtocol(): void {
    this.session.doDeleteProtocol();
  }

  protected refreshProtocol(): void {
    this.session.refreshProtocol();
  }

  setAttendance(member: Attendance, status: AttendanceStatus): void {
    this.session.setAttendance(member, status);
  }

  canAddVote(item: AgendaItem): boolean {
    return this.session.canAddVote(item);
  }

  openVoteDialog(item: AgendaItem): void {
    this.session.openVoteDialog(item);
  }

  closeVoteDialog(): void {
    this.session.closeVoteDialog();
  }

  submitVote(): void {
    this.session.submitVote();
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
    this.agendaSvc.onTopDrop(this.meeting()?.id ?? null, index, this.canManage());
  }

  addToAgenda(): void {
    const m = this.meeting();
    if (!m) return;
    this.agendaSvc.addToAgenda(m.id);
  }

  addFreetext(): void {
    const m = this.meeting();
    if (!m) return;
    this.agendaSvc.addFreetext(m.id);
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
  stateLabelOf(map: I18nMap | null | undefined): string {
    return resolveI18n(map, this.i18n.locale());
  }

  resolveLabel(map: I18nMap): string {
    return resolveI18n(map, this.i18n.locale());
  }

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

  attendanceKey(status: AttendanceStatus | 'unknown'): TranslationKey {
    return attendanceKey(status);
  }

  attBtnVariant(status: AttendanceStatus): 'primary' | 'secondary' | 'danger' {
    return attendanceButtonVariant(status);
  }

  attendanceIcon(status: AttendanceStatus): IconName {
    return attendanceIcon(status);
  }

  attBadgeVariant(status: AttendanceStatus): BadgeVariant {
    return attendanceBadgeVariant(status);
  }

  renderBody(body: string): string {
    return renderMarkdown(body);
  }
}
