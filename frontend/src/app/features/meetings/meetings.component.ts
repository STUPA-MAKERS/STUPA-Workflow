import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
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
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  AgendaItem,
  AssignableApplication,
  Attendance,
  AttendanceStatus,
  I18nMap,
  Meeting,
  MeetingMember,
  MeetingVote,
  Protocol,
  Uuid,
} from '@core/api/models';
import { WsService, type MeetingChannel } from '@core/ws/ws.service';
import type { ServerMessage } from '@core/ws/ws-messages';
import { BadgeComponent, type BadgeVariant } from '@shared/ui/badge/badge.component';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { CardComponent } from '@shared/ui/card/card.component';
import {
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  type IconName,
  SelectComponent,
  type SelectOption,
  TimeInputComponent,
} from '@shared/ui';
import { MarkdownEditorComponent } from '@shared/ui/markdown-editor/markdown-editor.component';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminOptionsService } from '../../pages/admin/admin-options.service';
import { MeetingDelegationCardComponent } from './meeting-delegation-card.component';
import { renderMarkdown } from './meetings.util';

/** Wartezeit nach der letzten Eingabe, bevor das Protokoll automatisch gespeichert wird (#56). */
const AUTOSAVE_DELAY_MS = 1000;

/**
 * Sitzungssteuerung + Protokoll-Editor (T-33, flows §5/§7).
 *
 *  - **Sitzungssteuerung** (RBAC `meeting.manage`): aktiven Antrag setzen, Votes
 *    live öffnen/schließen, Sitzungs-Status (live/geschlossen). Der Live-Stream
 *    (`/ws/meetings/{id}`) hält Status/Tally/Ergebnis ohne Reload aktuell und
 *    synchronisiert mit dem Beamer (api.md §4).
 *  - **Protokoll-Editor** (RBAC `protocol.write`): Markdown mit Snippet-Einfügen
 *    für Anträge/Abstimmungen (pytex-Shortcodes) + Live-Vorschau; `finalize`
 *    löst PDF/Versand aus (status `final` + Link).
 *
 * RBAC ist hier UX-Gating (nicht autoritativ) — der Server prüft jede Aktion.
 */
@Component({
  selector: 'app-meetings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    SelectComponent,
    DatepickerComponent,
    TimeInputComponent,
    DialogComponent,
    IconComponent,
    MarkdownEditorComponent,
    LocalizedDatePipe,
    MeetingDelegationCardComponent,
    NgTemplateOutlet,
  ],
  templateUrl: './meetings.component.html',
  styleUrl: './meetings.component.scss',
})
export class MeetingsComponent implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly ws = inject(WsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly useMock = inject(USE_MOCK_API);
  private readonly options = inject(AdminOptionsService);

  readonly loading = signal(false);
  readonly error = signal(false);
  readonly meeting = signal<Meeting | null>(null);
  readonly protocol = signal<Protocol | null>(null);
  /** Detail-Route (`/meetings/:id`) vs. Übersicht (`/meetings`). */
  readonly detailMode = signal(false);

  /** Anwesenheits-Roster der Sitzung (#Meetings/#55/#56). */
  readonly attendance = signal<Attendance[]>([]);
  /** Live-Zuschauer der Sitzungs-Seite (#live-viewers, via WS `viewers`). */
  readonly viewers = signal<string[]>([]);
  readonly savingAttendance = signal(false);
  readonly attendanceStatuses: readonly AttendanceStatus[] = ['present', 'excused', 'absent'];

  /** Tagesordnung + zuweisbare Abstimmungs-Anträge (#10/#58). */
  readonly agenda = signal<AgendaItem[]>([]);
  readonly assignable = signal<AssignableApplication[]>([]);
  readonly savingAgenda = signal(false);
  readonly agendaPick = signal<string>('');
  readonly agendaFreetext = signal<string>('');
  /** Inline-Umbenennen eines Freitext-TOP: aktiver TOP + Eingabe-Entwurf (#Sessions). */
  readonly renamingTopId = signal<Uuid | null>(null);
  readonly renameDraft = signal<string>('');

  /** Live-Abstimmung öffnen (#Meetings): Dialog-Zustand + Beschlussfrage/Optionen. */
  readonly voteDialogOpen = signal(false);
  private readonly voteItem = signal<AgendaItem | null>(null);
  readonly voteQuestion = signal<string>('');
  /** Feste Stimm-Optionen (kanonische Keys) — Pass/Fail braucht yes/no/abstain. */
  readonly FIXED_VOTE_OPTIONS = ['yes', 'no', 'abstain'] as const;
  readonly voteSecret = signal(false);
  // Optionale Beschluss-Parameter beim Öffnen (#5-4): Mehrheitsregel + Quorum.
  readonly voteMajorityRule = signal<'simple' | 'absolute' | 'two_thirds'>('simple');
  readonly voteEligibleCount = signal<string>('');
  readonly voteQuorumPercent = signal<string>('');
  readonly majorityRuleOptions = computed<SelectOption[]>(() =>
    (['simple', 'absolute', 'two_thirds'] as const).map((v) => ({
      value: v,
      label: this.i18n.translate(`vote.majority.${v}`),
    })),
  );
  readonly openingVote = signal(false);
  /** Anzeige-Label einer Stimm-Option (yes→Ja …); unbekannte roh. */
  voteOptionLabel(opt: string): string {
    const key = `vote.option.${opt}` as TranslationKey;
    const label = this.i18n.translate(key);
    return label === key ? opt : label;
  }
  readonly assignableOptions = computed<SelectOption[]>(() =>
    this.assignable().map((a) => {
      const title = a.title || a.applicationId;
      const state = this.stateLabelOf(a.stateLabel);
      // Status mit anzeigen (#5-4): welcher Antrag in welchem Abstimmungs-State.
      return { value: a.applicationId, label: state ? `${title} (${state})` : title };
    }),
  );

  /** Lokalisierter Flow-State-Name aus einer I18nMap (#5-4). */
  stateLabelOf(map: I18nMap | null | undefined): string {
    if (!map) return '';
    return map[this.i18n.locale()] ?? map['de'] ?? Object.values(map)[0] ?? '';
  }

  /** Initiales Laden der Übersicht-Timeline (erste Seite beider Richtungen). */
  readonly loadingList = signal(false);

  readonly saving = signal(false);
  /** Auto-Speichern-Status des aktuellen TOP-Texts (#56/#58). */
  readonly saveState = signal<'idle' | 'saving' | 'saved' | 'error'>('idle');
  /** Aktuell im rechten Editor gewählter TOP. */
  readonly selectedTopId = signal<Uuid | null>(null);
  readonly savingTop = signal(false);
  private bodyTimer: ReturnType<typeof setTimeout> | null = null;
  /** Poll-Fallback, solange der Worker das Protokoll rendert (Status »rendering«). */
  private renderPollTimer: ReturnType<typeof setTimeout> | null = null;
  private dragTopIndex: number | null = null;
  readonly finalizing = signal(false);
  readonly creating = signal(false);
  readonly newTitle = signal('');
  /** Optionales geplantes Datum für die neue Sitzung (#7), `YYYY-MM-DD`. */
  readonly newDate = signal('');
  /** Optionale geplante Uhrzeit (#34), `HH:mm`. */
  readonly newTime = signal('');
  /** Datums-/Zeit-Editor einer bereits angelegten, geplanten Sitzung (#7/#34). */
  readonly planDate = signal('');
  readonly planTime = signal('');
  readonly savingDate = signal(false);
  /** Pflicht-Gremium für die neue Sitzung (#68); leer ⇒ Submit gesperrt. */
  readonly newGremiumId = signal('');
  /** Protokollant der neuen Sitzung — wählbar beim Anlegen, Pflicht spätestens vor
   *  dem Start. Kandidaten = aktuelle Mitglieder des gewählten Gremiums. */
  readonly newProtokollant = signal('');
  readonly createMembers = signal<MeetingMember[]>([]);
  readonly createProtokollantOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('meetings.protokollant.none') },
    ...this.createMembers().map((m) => ({
      value: m.principalId,
      label: m.displayName || m.email || m.principalId,
    })),
  ]);
  /** Gremien als Dropdown-Optionen (echte Liste, `/gremien`). */
  readonly gremiumOptions = signal<SelectOption[]>([]);
  /** Gremium-Filter der Übersicht (''=alle). Quelle: Mitglieds-Gremien (#meetings-filter). */
  readonly gremiumFilter = signal<string>('');
  readonly filterGremiumOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('meetings.list.allCommittees') },
    ...this.auth.gremien().map((g) => ({ value: g.id, label: g.name })),
  ]);
  /** Sitzung-anlegen-Dialog offen (#27). */
  readonly createOpen = signal(false);

  // --- Timeline (#104) — server-seitiges Keyset-Lazy-Loading ----------------
  /** Seitengröße je Nachlade-Schritt (beide Richtungen). */
  private readonly PAGE = 15;

  /** Anstehende Sitzungen, chronologisch vorwärts (frühestes oben). */
  readonly upcomingItems = signal<Meeting[]>([]);
  /** Vergangene Sitzungen, chronologisch (ältestes oben, jüngstes am „jetzt"). */
  readonly pastItems = signal<Meeting[]>([]);
  /** Cursor der jeweils nächsten Seite (``null`` ⇒ Richtung erschöpft). */
  private upcomingCursor: string | null = null;
  private pastCursor: string | null = null;
  readonly upcomingHasMore = signal(false);
  readonly pastHasMore = signal(false);
  readonly loadingUpcoming = signal(false);
  readonly loadingPast = signal(false);
  private didInitialScroll = false;

  readonly timelineScroll = viewChild<ElementRef<HTMLElement>>('tlScroll');
  readonly nowMarker = viewChild<ElementRef<HTMLElement>>('nowMarker');

  /** „Frühere Sitzungen laden"-Affordanz (oben). */
  readonly hasMorePast = computed(() => this.pastHasMore());
  /** Übersicht leer (nach dem Laden keine Sitzung in beiden Richtungen). */
  readonly timelineEmpty = computed(
    () => !this.upcomingItems().length && !this.pastItems().length,
  );

  /**
   * Scroll-getriebenes Nachladen: nahe dem oberen Rand ⇒ ältere Vergangenheit,
   * nahe dem unteren Rand ⇒ weitere Zukunft. Beide serverseitig per Cursor.
   */
  onTimelineScroll(el: HTMLElement): void {
    if (el.scrollTop <= 80) this.loadMorePast(el);
    if (el.scrollHeight - el.scrollTop - el.clientHeight <= 80) this.loadMoreUpcoming();
  }

  /** Gremium-Filter umschalten → Timeline neu laden (#meetings-filter). */
  selectGremiumFilter(id: string): void {
    this.gremiumFilter.set(id);
    this.loadList();
  }

  /** Nächste Vergangenheits-Seite laden + Scroll-Position über die neue Höhe halten. */
  loadMorePast(el: HTMLElement): void {
    if (this.loadingPast() || !this.pastHasMore() || this.pastCursor === null) return;
    this.loadingPast.set(true);
    const prevHeight = el.scrollHeight;
    this.api
      .listMeetingsTimeline({
        direction: 'past',
        cursor: this.pastCursor,
        limit: this.PAGE,
        gremiumId: this.gremiumFilter() || undefined,
      })
      .subscribe({
        next: (page) => {
          this.loadingPast.set(false);
          // Seite ist neueste-zuerst ⇒ umgedreht oben anfügen (älteste bleiben oben).
          this.pastItems.update((cur) => [...[...page.items].reverse(), ...cur]);
          this.pastCursor = page.nextCursor;
          this.pastHasMore.set(page.nextCursor !== null);
          requestAnimationFrame(() => {
            el.scrollTop += el.scrollHeight - prevHeight;
          });
        },
        error: () => this.loadingPast.set(false),
      });
  }

  /** Nächste Zukunfts-Seite laden + unten anfügen. */
  loadMoreUpcoming(): void {
    if (this.loadingUpcoming() || !this.upcomingHasMore() || this.upcomingCursor === null)
      return;
    this.loadingUpcoming.set(true);
    this.api
      .listMeetingsTimeline({
        direction: 'upcoming',
        cursor: this.upcomingCursor,
        limit: this.PAGE,
        gremiumId: this.gremiumFilter() || undefined,
      })
      .subscribe({
        next: (page) => {
          this.loadingUpcoming.set(false);
          this.upcomingItems.update((cur) => [...cur, ...page.items]);
          this.upcomingCursor = page.nextCursor;
          this.upcomingHasMore.set(page.nextCursor !== null);
        },
        error: () => this.loadingUpcoming.set(false),
      });
  }

  /** Eine geänderte Sitzung in beiden Richtungen ersetzen (Settings-Save). */
  private replaceInTimeline(updated: Meeting): void {
    const repl = (list: Meeting[]): Meeting[] =>
      list.map((x) => (x.id === updated.id ? updated : x));
    this.upcomingItems.update(repl);
    this.pastItems.update(repl);
  }

  /** Eine gelöschte Sitzung aus beiden Richtungen entfernen. */
  private removeFromTimeline(id: Uuid): void {
    const rm = (list: Meeting[]): Meeting[] => list.filter((x) => x.id !== id);
    this.upcomingItems.update(rm);
    this.pastItems.update(rm);
  }

  openCreate(): void {
    this.newProtokollant.set('');
    this.createMembers.set([]);
    // Vorbelegtes Gremium (z. B. aus dem Übersichtsfilter): direkt Mitglieder laden.
    if (this.newGremiumId()) this.loadCreateMembers(this.newGremiumId());
    this.createOpen.set(true);
  }

  /** Gremium im Anlegen-Dialog wechseln → Protokollant-Kandidaten neu laden. */
  onCreateGremiumChange(gremiumId: string): void {
    this.newGremiumId.set(gremiumId);
    this.newProtokollant.set('');
    this.createMembers.set([]);
    if (gremiumId) this.loadCreateMembers(gremiumId);
  }

  private loadCreateMembers(gremiumId: string): void {
    this.api.listMeetingMembers(gremiumId).subscribe({
      next: (rows) => this.createMembers.set(rows),
      error: () => this.createMembers.set([]),
    });
  }

  /** Globale Verwalter-Rechte — Gating der Übersicht/Anlegen (ohne geladene Sitzung). */
  readonly canManageAny = computed(() => this.auth.can('meeting.manage'));
  /** Sitzung anlegen: globale `meeting.manage` ODER Vorstand/Manager (Gremium-Rolle
   *  mit `session.manage`) in mindestens einem Gremium — gremium-genau wie das
   *  Backend (`MeetingService.can_manage`). */
  readonly canCreate = computed(
    () => this.canManageAny() || this.auth.sessionManageGremien().length > 0,
  );
  /** Per-Sitzung-Flags aus der geladenen Sitzung (Backend, gremium-genau). */
  readonly canManage = computed(() => this.meeting()?.canManage ?? this.canManageAny());
  readonly canWrite = computed(() => this.meeting()?.canWrite ?? false);
  readonly canManageVotes = computed(() => this.meeting()?.canManageVotes ?? false);
  readonly canVote = computed(() => this.meeting()?.canVote ?? false);
  readonly canWriteGlobal = computed(() => this.auth.can('protocol.write'));
  /** Mitglied irgendeines Gremiums → darf die (gefilterte) Sitzungsübersicht sehen. */
  readonly inAnyCommittee = computed(() => this.auth.gremien().length > 0);
  /** Stellvertreter-Pool-Mitglied → darf die (gefilterte) Timeline sehen (#7). */
  readonly inSubstitutePool = computed(() => this.auth.inSubstitutePool());
  /** Darf die (serverseitig gefilterte) Sitzungsübersicht/Timeline sehen. */
  readonly showOverview = computed(
    () =>
      this.canManageAny() ||
      this.canWriteGlobal() ||
      this.inAnyCommittee() ||
      this.inSubstitutePool(),
  );
  /** Übersicht ohne Detail-Route, ohne Verwalter-/Schreibrecht, ohne Gremium-
   *  Mitgliedschaft **und** ohne Pool-Zugehörigkeit ⇒ keine Berechtigung (#sessions/#7). */
  readonly showForbidden = computed(
    () =>
      !this.detailMode() &&
      !this.canManageAny() &&
      !this.canWriteGlobal() &&
      !this.inAnyCommittee() &&
      !this.inSubstitutePool(),
  );
  /** Ist der angemeldete Nutzer der für DIESE Sitzung gewählte Protokollant? */
  readonly isProtokollant = computed(() => {
    const m = this.meeting();
    const uid = this.auth.userId();
    return !!m && !!m.protokollantId && !!uid && m.protokollantId === uid;
  });
  /** Live-Verfolgung (Protokoll lesen + offene Abstimmungen mitstimmen) statt
   *  Edit-/Manager-View. Sobald ein Protokollant gewählt ist, bekommt **nur**
   *  dieser den Manager-View — alle anderen (auch Verwalter) die Live-Ansicht.
   *  Ohne gewählten Protokollant greift das alte Schreib-/Verwaltungs-Gate,
   *  damit eine frisch angelegte Sitzung vor dem Start nicht in einer Sackgasse
   *  landet (Zuweisung erfolgt dann aus der Übersicht). */
  readonly isFollower = computed(() => {
    const m = this.meeting();
    if (!m) return false;
    if (m.protokollantId) return !this.isProtokollant();
    return !m.canWrite && !m.canManage;
  });
  /** Beamer-Anzeige (nur aktuelle Frage + Live-Ergebnis, keine Dialoge). */
  readonly beamerMode = signal(false);

  /** Einstellungs-Dialog (Protokollant + Datum/Zeit) — aus Toolbar ODER Listen-Edit. */
  readonly settingsMeeting = signal<Meeting | null>(null);
  readonly settingsRoster = signal<Attendance[]>([]);
  readonly settingsProtokollant = signal<string>('');
  readonly settingsDate = signal<string>('');
  readonly settingsTime = signal<string>('');
  readonly savingSettings = signal(false);
  /** Geschlossene Sitzung (#15): Einstellungen KOMPLETT gesperrt — gilt auch im
   *  Listen-Edit (der Status reist im Meeting-Objekt mit). */
  readonly settingsLocked = computed(() => this.settingsMeeting()?.status === 'closed');
  /** Protokollant zusätzlich gesperrt, sobald das Protokoll finalisiert ist (#15);
   *  Protokoll-Status ist nur in der Detail-Ansicht der offenen Sitzung bekannt. */
  readonly protokollantLocked = computed(
    () =>
      this.meeting()?.id === this.settingsMeeting()?.id && !!this.protocol()?.isFinal,
  );
  /** Protokollant-Auswahl aus dem Anwesenheits-Roster (alle Gremium-Mitglieder). */
  readonly protokollantOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('meetings.protokollant.none') },
    ...this.settingsRoster().map((a) => ({
      value: a.principalId,
      label: a.displayName || a.email || a.principalId,
    })),
  ]);
  /** Löschen-Bestätigung (Toolbar ODER Listen-Zeile). */
  readonly confirmDeleteMeeting = signal<Meeting | null>(null);
  readonly deletingMeeting = signal(false);
  /** Bestätigungs-Dialog fürs (unwiderrufliche) Schließen der Sitzung. */
  readonly closeConfirmOpen = signal(false);
  /** Casting-Status je Vote (für Mitglied/Protokollant-Stimmabgabe). */
  readonly casting = signal<Uuid | null>(null);
  readonly deletingVote = signal<Uuid | null>(null);
  /** Eigene Stimmwahl je Vote (lokal, fürs Hervorheben der gewählten Option). */
  private readonly myChoices = signal<Record<string, string>>({});
  myChoice(voteId: Uuid): string | null {
    return this.myChoices()[voteId] ?? null;
  }

  /** Votes eines TOP (gruppiert über agendaItemId). */
  votesForTop(topId: Uuid): MeetingVote[] {
    return (this.meeting()?.votes ?? []).filter((v) => v.agendaItemId === topId);
  }
  /** Sitzungs-Votes ohne TOP-Bindung (Bestand/aktiv) — in der Steuerung gelistet. */
  readonly looseVotes = computed<MeetingVote[]>(() =>
    (this.meeting()?.votes ?? []).filter((v) => !v.agendaItemId),
  );

  /** Aktuell gewählter TOP (rechter Editor) + sein 0-basierter Index. */
  readonly selectedTop = computed<AgendaItem | null>(
    () => this.agenda().find((a) => a.id === this.selectedTopId()) ?? null,
  );
  readonly selectedIndex = computed(() =>
    this.agenda().findIndex((a) => a.id === this.selectedTopId()),
  );

  private channel: MeetingChannel | null = null;

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      const id = pm.get('id');
      this.detailMode.set(!!id);
      if (id) {
        this.loadMeeting(id);
      } else {
        // Übersichts-Route `/meetings`: einzelne Sitzung lösen + Liste laden (#104).
        this.meeting.set(null);
        this.loadList();
      }
    });
    // Timeline (#104): einmalig auf den „jetzt"-Marker positionieren, sobald die
    // Liste geladen + gerendert ist — Anstehendes sichtbar, Vergangenes per Hochscrollen.
    effect(() => {
      const marker = this.nowMarker()?.nativeElement;
      const scroller = this.timelineScroll()?.nativeElement;
      // Abhängigkeiten: neu positionieren, sobald beide Richtungen eingetroffen sind.
      this.pastItems();
      this.upcomingItems();
      if (marker && scroller && !this.didInitialScroll && !this.loadingList()) {
        this.didInitialScroll = true;
        requestAnimationFrame(() => {
          scroller.scrollTop = Math.max(0, marker.offsetTop - 8);
        });
      }
    });
    // Timeline-Höhe auf den freien Viewport-Rest setzen, sobald sie (neu) erscheint
    // bzw. ihr Inhalt wächst (#sitzungen-100vh). Resize triggert separat (Listener).
    effect(() => {
      const el = this.timelineScroll();
      // Abhängigkeiten: (Wieder-)Erscheinen + Inhaltsmenge.
      this.timelineEmpty();
      this.loadingList();
      this.pastItems();
      this.upcomingItems();
      if (el) this.scheduleMeasure();
    });
    window.addEventListener('resize', this.onResize, { passive: true });
    // Gremien-Liste für das Anlege-Dropdown (#68) — nur wer Sitzungen verwalten
    // darf. Ohne globale `meeting.manage` werden nur die SELBST verwalteten
    // Gremien angeboten (Vorstand/Manager via Gremium-Rolle) — alles andere
    // würde der Server beim Anlegen ohnehin mit 403 ablehnen.
    if (this.canCreate()) {
      this.options
        .gremiumOptions()
        .pipe(takeUntilDestroyed())
        .subscribe({
          next: (opts) => {
            if (this.canManageAny()) {
              this.gremiumOptions.set(opts);
              return;
            }
            const managed = new Set(this.auth.sessionManageGremien());
            this.gremiumOptions.set(opts.filter((o) => managed.has(o.value)));
          },
          error: () => this.gremiumOptions.set([]),
        });
    }
  }

  ngOnDestroy(): void {
    this.channel?.close();
    if (this.bodyTimer !== null) clearTimeout(this.bodyTimer);
    if (this.renderPollTimer !== null) clearTimeout(this.renderPollTimer);
    window.removeEventListener('resize', this.onResize);
    if (this.measureRaf !== null) cancelAnimationFrame(this.measureRaf);
  }

  // --- Timeline-Höhe (#sitzungen-100vh) ------------------------------------
  /** Mindesthöhe der Timeline (px), falls der Viewport sehr klein ist. */
  private readonly TIMELINE_MIN_PX = 192;
  private measureRaf: number | null = null;
  private readonly onResize = (): void => this.scheduleMeasure();

  /** Messung gebündelt auf den nächsten Frame (Layout muss gesetzt sein). */
  private scheduleMeasure(): void {
    if (this.measureRaf !== null) cancelAnimationFrame(this.measureRaf);
    this.measureRaf = requestAnimationFrame(() => {
      this.measureRaf = null;
      this.measureTimeline();
    });
  }

  /**
   * Timeline-Höhe = Viewport − alles darüber (Header/Breadcrumb/H1/Toolbar) −
   * alles darunter (Footer + Main-Unterrand). Scroll-unabhängig gemessen
   * (`rect.top + scrollY` = absoluter Layout-Offset), damit die Seite selbst
   * nicht scrollt und nur die Timeline intern scrollt.
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

  // --- laden / anlegen -----------------------------------------------------
  private loadMeeting(id: Uuid): void {
    this.loading.set(true);
    this.error.set(false);
    this.api.getMeeting(id).subscribe({
      next: (m) => {
        this.loading.set(false);
        this.adoptMeeting(m);
      },
      error: () => {
        this.loading.set(false);
        this.error.set(true);
      },
    });
  }

  private adoptMeeting(m: Meeting): void {
    this.meeting.set(m);
    this.planDate.set(m.date ?? '');
    this.planTime.set(m.startTime ?? '');
    this.connectLive(m.id);
    // Bestehendes Protokoll per GET lesen (kein Write-Rate-Limit, #429);
    // angelegt wird nur explizit über den Button (POST, loadProtocol).
    if (m.protocolId && this.canWrite()) this.refreshProtocol();
    this.loadAttendance(m.id);
    this.loadAgenda(m.id);
  }

  /**
   * Timeline initial laden (#104): erste Zukunfts- **und** Vergangenheits-Seite
   * parallel, danach wird einmalig auf „jetzt" gescrollt (Effect oben).
   */
  private loadList(): void {
    // Auch reine Gremium-Mitglieder sehen die (serverseitig auf ihre Gremien
    // gefilterte) Timeline — das alte canManage/canWrite-Gate ließ Mitglieder
    // ohne Schreibrecht vor einer leeren Seite stehen (#sessions-visibility).
    if (!this.canManageAny() && !this.canWriteGlobal() && !this.inAnyCommittee()) return;
    this.didInitialScroll = false;
    this.upcomingItems.set([]);
    this.pastItems.set([]);
    this.upcomingCursor = null;
    this.pastCursor = null;
    this.upcomingHasMore.set(false);
    this.pastHasMore.set(false);
    this.loadingList.set(true);
    forkJoin({
      upcoming: this.api.listMeetingsTimeline({
        direction: 'upcoming',
        limit: this.PAGE,
        gremiumId: this.gremiumFilter() || undefined,
      }),
      past: this.api.listMeetingsTimeline({
        direction: 'past',
        limit: this.PAGE,
        gremiumId: this.gremiumFilter() || undefined,
      }),
    }).subscribe({
      next: ({ upcoming, past }) => {
        this.loadingList.set(false);
        this.upcomingItems.set(upcoming.items);
        this.upcomingCursor = upcoming.nextCursor;
        this.upcomingHasMore.set(upcoming.nextCursor !== null);
        // „past" kommt neueste-zuerst ⇒ umdrehen: ältestes oben, jüngstes am „jetzt".
        this.pastItems.set([...past.items].reverse());
        this.pastCursor = past.nextCursor;
        this.pastHasMore.set(past.nextCursor !== null);
      },
      error: () => {
        this.loadingList.set(false);
        this.upcomingItems.set([]);
        this.pastItems.set([]);
      },
    });
  }

  create(event: Event): void {
    event.preventDefault();
    const title = this.newTitle().trim();
    const gremiumId = this.newGremiumId();
    const date = this.newDate().trim();
    const startTime = this.newTime().trim();
    // Datum + Uhrzeit sind Pflicht (Termin der Sitzung); Submit ist sonst gesperrt.
    if (!title || !gremiumId || !date || !startTime || this.creating()) return;
    this.creating.set(true);
    this.api
      .createMeeting({
        title,
        gremiumId,
        date,
        startTime,
        protokollantId: this.newProtokollant() || null,
      })
      .subscribe({
      next: (m) => {
        this.creating.set(false);
        this.newTitle.set('');
        this.newGremiumId.set('');
        this.newDate.set('');
        this.newTime.set('');
        this.newProtokollant.set('');
        this.createMembers.set([]);
        this.createOpen.set(false);
        this.toast.success(this.i18n.translate('meetings.toast.created'));
        // Auf die Detail-Route navigieren, damit die Sitzung wiederauffindbar ist (#104).
        void this.router.navigate(['/meetings', m.id]);
      },
      error: () => {
        this.creating.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.createFailed'));
      },
    });
  }

  /** Eine Sitzung aus der Liste öffnen → Detail-Route (#104). */
  openMeeting(id: Uuid): void {
    void this.router.navigate(['/meetings', id]);
  }

  // --- Sitzungssteuerung ---------------------------------------------------
  setStatus(status: 'live' | 'closed'): void {
    const m = this.meeting();
    if (!m) return;
    // »closed« ist terminal — keine Wiedereröffnung (der Server lehnt es ohnehin ab).
    if (m.status === 'closed') return;
    // Start verlangt einen Protokollanten (Schriftführung des Protokolls). Vorab
    // prüfen, damit der 409 des Servers nicht erst nach dem Klick auftaucht.
    if (status === 'live' && !m.protokollantId) {
      this.toast.error(this.i18n.translate('meetings.toast.protokollantRequired'));
      return;
    }
    this.api.patchMeeting(m.id, { status }).subscribe({
      next: (updated) => {
        this.meeting.set(updated);
        // Protokoll entsteht beim Start (Backend) — direkt per GET nachladen.
        if (updated.status === 'live' && updated.protocolId && this.canWrite()) {
          this.refreshProtocol();
        }
      },
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  /** Sitzung unwiderruflich schließen → Status closed + Protokoll finalisieren. */
  closeMeeting(): void {
    const m = this.meeting();
    if (!m || this.finalizing()) return;
    this.api.patchMeeting(m.id, { status: 'closed' }).subscribe({
      next: (updated) => {
        this.meeting.set(updated);
        const proto = this.protocol();
        // Finalisieren passiert implizit: PDF rendern + an MAIL_LIST versenden.
        if (proto && !proto.isLocked) {
          this.finalize();
        }
      },
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  /** Geplantes Datum einer (geplanten) Sitzung vorab setzen (#7, PATCH date). */
  savePlannedDate(): void {
    const m = this.meeting();
    const date = this.planDate().trim();
    if (!m || !date || this.savingDate()) return;
    this.savingDate.set(true);
    this.api.patchMeeting(m.id, { date, startTime: this.planTime().trim() || null }).subscribe({
      next: (updated) => {
        this.savingDate.set(false);
        this.meeting.set(updated);
        this.toast.success(this.i18n.translate('meetings.toast.dateSaved'));
      },
      error: () => {
        this.savingDate.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  setActive(applicationId: Uuid): void {
    const m = this.meeting();
    if (!m) return;
    this.api.patchMeeting(m.id, { activeApplicationId: applicationId }).subscribe({
      next: (updated) => this.meeting.set(updated),
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  openVote(voteId: Uuid): void {
    this.api.openVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'open' }),
      error: (err: unknown) => this.voteActionFailed(err),
    });
  }

  closeVote(voteId: Uuid): void {
    this.api.closeVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'closed' }),
      error: (err: unknown) => this.voteActionFailed(err),
    });
  }

  /** Abstimmung abbrechen (#12): open → cancelled, kein Ergebnis/Branch — der
   *  Ausweg, wenn das Quorum nicht zustande kommt (Schließen ist dann blockiert). */
  cancelVote(voteId: Uuid): void {
    this.api.cancelVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'cancelled' }),
      error: (err: unknown) => this.voteActionFailed(err),
    });
  }

  /** Vote-Aktion fehlgeschlagen: konkreten Server-Grund zeigen (z. B. 409 »Antrag
      nicht im vote-State« / »Vote storniert«) statt eines generischen Toasts, und
      den Sitzungs-State nachladen — der Vote kann serverseitig z. B. auf
      ``cancelled`` geflippt sein (#abort-vote). */
  private voteActionFailed(err: unknown): void {
    const detail = this.errorDetail(err);
    const base = this.i18n.translate('meetings.toast.actionFailed');
    this.toast.error(detail ? `${base}: ${detail}` : base);
    const m = this.meeting();
    if (m) {
      this.api.getMeeting(m.id).subscribe({
        next: (updated) => this.meeting.set(updated),
        error: () => {},
      });
    }
  }

  // --- Protokoll: TOPs links, pro-TOP-Editor rechts (#58) ------------------
  /** Bestehendes Protokoll per GET nachladen (kein Write-Rate-Limit, #429). */
  private refreshProtocol(): void {
    const m = this.meeting();
    if (!m) return;
    this.api.getProtocol(m.id).subscribe({
      next: (proto) => {
        this.protocol.set(proto);
        this.watchRendering(proto);
      },
      error: () => {},
    });
  }

  /** Status-Flip nach dem Hintergrund-Render anwenden (+ Toast final/fehlgeschlagen).

      `rendering → draft` heißt: der Worker hat den Render aufgegeben und
      zurückgerollt — das Protokoll ist wieder editier- und finalisierbar. */
  private applyProtocolUpdate(updated: Protocol): void {
    const prev = this.protocol();
    this.protocol.set(updated);
    if (prev?.status === 'rendering') {
      if (updated.isFinal) {
        this.toast.success(this.i18n.translate('meetings.toast.finalized'));
      } else if (updated.status === 'draft') {
        this.toast.error(this.i18n.translate('meetings.toast.finalizeFailed'));
      }
    }
    this.watchRendering(updated);
  }

  /** Solange `rendering`: Protokoll zyklisch nachladen — Fallback, falls der
      `meeting_state`-Broadcast des Workers verloren geht. */
  private watchRendering(proto: Protocol): void {
    if (this.renderPollTimer !== null) clearTimeout(this.renderPollTimer);
    if (proto.status !== 'rendering' || !this.canWrite()) return;
    this.renderPollTimer = setTimeout(() => {
      this.renderPollTimer = null;
      const m = this.meeting();
      if (!m) return;
      // GET statt POST: der Poll darf das Default-Write-Rate-Limit nicht
      // aufbrauchen (429 nach wenigen Minuten, #429).
      this.api.getProtocol(m.id).subscribe({
        next: (updated) => this.applyProtocolUpdate(updated),
        error: () => this.watchRendering(proto),
      });
    }, 4000);
  }

  selectTop(id: Uuid): void {
    this.selectedTopId.set(id);
  }

  /** Markdown-Text eines TOP debounced an den Server (PATCH …/agenda/{id}). */
  onTopBodyChange(itemId: Uuid, body: string): void {
    const m = this.meeting();
    if (!m) return;
    if (this.bodyTimer !== null) clearTimeout(this.bodyTimer);
    this.saveState.set('idle');
    this.bodyTimer = setTimeout(() => {
      this.bodyTimer = null;
      this.savingTop.set(true);
      this.saveState.set('saving');
      this.api.setAgendaBody(m.id, itemId, body).subscribe({
        next: (rows) => {
          this.savingTop.set(false);
          this.agenda.set(rows);
          this.saveState.set('saved');
        },
        error: () => {
          this.savingTop.set(false);
          this.saveState.set('error');
        },
      });
    }, AUTOSAVE_DELAY_MS);
  }

  // --- TOP-Reihenfolge (Drag&Drop) -----------------------------------------
  onTopDragStart(index: number): void {
    this.dragTopIndex = index;
  }

  onTopDragOver(event: DragEvent): void {
    if (this.dragTopIndex !== null) event.preventDefault();
  }

  onTopDrop(index: number): void {
    const from = this.dragTopIndex;
    this.dragTopIndex = null;
    const m = this.meeting();
    if (from === null || from === index || !m) return;
    const items = [...this.agenda()];
    const [moved] = items.splice(from, 1);
    items.splice(index, 0, moved);
    this.agenda.set(items); // optimistisch
    this.api.reorderAgenda(m.id, items.map((i) => i.id)).subscribe({
      next: (rows) => this.agenda.set(rows),
      error: () => {
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
        if (m) this.loadAgenda(m.id);
      },
    });
  }

  /** Protokoll-Markdown aus den geordneten TOPs zusammensetzen (#58). */
  private assembleMarkdown(): string {
    return this.agenda()
      .map((t) => {
        // Top-level `#` → pytex' Protokoll-Variante nummeriert es selbst als „TOP n"
        // (\thesection). Daher KEIN manuelles „TOP n:"-Präfix und kein `##` (das würde
        // als „0.n" nummeriert + „TOP n:" doppelt). Frontmatter-`title` verhindert, dass
        // das erste `#` als Titelseite verbraucht wird.
        const heading = `# ${t.title?.trim() || 'Tagesordnungspunkt'}`;
        const ref = t.applicationId ? `\n\n:::antrag{#${t.applicationId}}\n:::` : '';
        const body = t.body?.trim() ? `\n\n${t.body.trim()}` : '';
        return `${heading}${ref}${body}`;
      })
      .join('\n\n');
  }

  finalize(): void {
    const proto = this.protocol();
    // `isLocked` deckt auch »rendering« ab: kein zweiter Anstoß, kein 409 beim PATCH.
    if (!proto || proto.isLocked || this.finalizing() || this.savingTop()) return;
    this.finalizing.set(true);
    // Erst die TOP-Texte zum Protokoll-Markdown zusammensetzen + speichern,
    // dann finalisieren/rendern.
    this.api.updateProtocol(proto.id, this.assembleMarkdown()).subscribe({
      next: (saved) => {
        this.protocol.set(saved);
        this.doFinalize(saved.id);
      },
      error: () => {
        this.finalizing.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.saveFailed'));
      },
    });
  }

  private doFinalize(protocolId: Uuid): void {
    this.api.finalizeProtocol(protocolId).subscribe({
      next: (updated) => {
        this.finalizing.set(false);
        this.protocol.set(updated);
        if (updated.isFinal) {
          // Sync-Pfad (DEV ohne Redis): direkt final.
          this.toast.success(this.i18n.translate('meetings.toast.finalized'));
        } else {
          // Async-Pfad: der Worker rendert im Hintergrund — Tag zeigt »Wird gerendert«,
          // der Abschluss kommt per WS-Broadcast bzw. Poll-Fallback.
          this.toast.success(this.i18n.translate('meetings.toast.renderQueued'));
          this.watchRendering(updated);
        }
      },
      error: (err: unknown) => {
        this.finalizing.set(false);
        // Render-/Compile-Fehler (400) tragen einen konkreten Grund — anzeigen.
        const detail = this.errorDetail(err);
        this.toast.error(
          detail
            ? `${this.i18n.translate('meetings.toast.finalizeFailed')}: ${detail}`
            : this.i18n.translate('meetings.toast.finalizeFailed'),
        );
      },
    });
  }

  /** Konkrete `problem+json`-`detail`-Meldung aus einem HTTP-Fehler (oder leer). */
  private errorDetail(err: unknown): string {
    const body = (err as { error?: { detail?: string } } | null)?.error;
    return typeof body?.detail === 'string' ? body.detail : '';
  }

  // --- Anwesenheit (#Meetings/#55/#56) -------------------------------------
  private loadAttendance(meetingId: Uuid): void {
    this.api.listAttendance(meetingId).subscribe({
      next: (rows) => this.attendance.set(rows),
      error: () => this.attendance.set([]),
    });
  }

  setAttendance(member: Attendance, status: AttendanceStatus): void {
    const m = this.meeting();
    if (!m || this.savingAttendance() || member.status === status) return;
    this.savingAttendance.set(true);
    // Eigene Anwesenheit als »self« markieren; Mitglieder setzt die Leitung.
    const req = member.isSelf
      ? this.api.setOwnAttendance(m.id, status)
      : this.api.setMemberAttendance(m.id, member.principalId, status);
    req.subscribe({
      next: (rows) => {
        this.savingAttendance.set(false);
        this.attendance.set(rows);
      },
      error: () => {
        this.savingAttendance.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  attendanceKey(status: AttendanceStatus | 'unknown'): TranslationKey {
    return `meetings.attendance.${status}` as TranslationKey;
  }

  attBtnVariant(status: AttendanceStatus): 'primary' | 'secondary' | 'danger' {
    return status === 'present' ? 'primary' : status === 'excused' ? 'secondary' : 'danger';
  }

  /** Kompaktes Icon je Anwesenheits-Status: anwesend check, entschuldigt halb, abwesend remove. */
  attendanceIcon(status: AttendanceStatus): IconName {
    return status === 'present' ? 'check' : status === 'excused' ? 'half' : 'remove';
  }

  attBadgeVariant(status: AttendanceStatus): BadgeVariant {
    return status === 'present' ? 'success' : status === 'excused' ? 'warning' : 'danger';
  }

  // --- Tagesordnung (#10/#58) ----------------------------------------------
  private loadAgenda(meetingId: Uuid): void {
    this.api.listAgenda(meetingId).subscribe({
      next: (rows) => {
        this.agenda.set(rows);
        // Bleibt der gewählte TOP gültig? Sonst den ersten wählen.
        const sel = this.selectedTopId();
        if (!sel || !rows.some((r) => r.id === sel)) {
          this.selectedTopId.set(rows[0]?.id ?? null);
        }
      },
      error: () => this.agenda.set([]),
    });
    if (this.canManage()) this.refreshAssignable(meetingId);
  }

  private refreshAssignable(meetingId: Uuid): void {
    this.api.listAssignableApplications(meetingId).subscribe({
      next: (rows) => this.assignable.set(rows),
      error: () => this.assignable.set([]),
    });
  }

  addToAgenda(): void {
    const m = this.meeting();
    const appId = this.agendaPick();
    if (!m || !appId || this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.addAgendaItem(m.id, appId).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.agendaPick.set('');
        this.refreshAssignable(m.id);
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  addFreetext(): void {
    const m = this.meeting();
    const title = this.agendaFreetext().trim();
    if (!m || !title || this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.addAgendaFreetext(m.id, title).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.agendaFreetext.set('');
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  removeFromAgenda(itemId: Uuid): void {
    const m = this.meeting();
    if (!m || this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.removeAgendaItem(m.id, itemId).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.refreshAssignable(m.id);
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  /** Inline-Umbenennen eines Freitext-TOP starten (nur ohne Antrags-Bindung). */
  startRename(item: AgendaItem): void {
    if (item.applicationId) return;
    this.renamingTopId.set(item.id);
    this.renameDraft.set(item.title ?? '');
  }

  cancelRename(): void {
    this.renamingTopId.set(null);
    this.renameDraft.set('');
  }

  /** Neuen Titel eines Freitext-TOP speichern (PATCH …/agenda/{id} { title }). */
  renameTop(item: AgendaItem): void {
    // Bereits abgebrochen/umgeschaltet? Nichts tun (verhindert doppelten Blur-Save).
    if (this.renamingTopId() !== item.id) return;
    const m = this.meeting();
    const title = this.renameDraft().trim();
    // Leer oder unverändert ⇒ nur schließen, kein Request.
    if (!m || item.applicationId || !title || title === (item.title ?? '')) {
      this.cancelRename();
      return;
    }
    this.renamingTopId.set(null);
    this.savingAgenda.set(true);
    this.api.renameAgendaItem(m.id, item.id, title).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.renameDraft.set('');
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }


  // --- Live-Abstimmung/Beschlussfrage öffnen (#Sessions) -------------------
  /** App-TOP: genau eine Abstimmung; Freitext-TOP: beliebig viele Beschlussfragen. */
  canAddVote(item: AgendaItem): boolean {
    return !item.applicationId || this.votesForTop(item.id).length === 0;
  }

  openVoteDialog(item: AgendaItem): void {
    this.voteItem.set(item);
    this.voteQuestion.set(item.title ?? '');
    this.voteSecret.set(false);
    this.voteMajorityRule.set('simple');
    this.voteEligibleCount.set('');
    this.voteQuorumPercent.set('');
    this.voteDialogOpen.set(true);
  }

  closeVoteDialog(): void {
    this.voteDialogOpen.set(false);
  }

  submitVote(): void {
    const m = this.meeting();
    const item = this.voteItem();
    const options = [...this.FIXED_VOTE_OPTIONS];
    if (!m || !item || this.openingVote()) return;
    this.openingVote.set(true);
    this.api
      .openMeetingVote(m.id, {
        agendaItemId: item.id,
        question: this.voteQuestion().trim() || null,
        options,
        secret: this.voteSecret(),
        majorityRule: this.voteMajorityRule(),
        eligibleCount: this.voteEligibleCount().trim()
          ? Number(this.voteEligibleCount())
          : null,
        quorumPercent: this.voteQuorumPercent().trim()
          ? Number(this.voteQuorumPercent())
          : null,
      })
      .subscribe({
        next: (updated) => {
          this.openingVote.set(false);
          this.voteDialogOpen.set(false);
          this.meeting.set(updated);
          this.toast.success(this.i18n.translate('meetings.toast.voteOpened'));
        },
        error: (err: unknown) => {
          this.openingVote.set(false);
          // Konkreten Grund zeigen (z. B. 409 »Antrag nicht im vote-State«).
          const detail = this.errorDetail(err);
          const base = this.i18n.translate('meetings.toast.actionFailed');
          this.toast.error(detail ? `${base}: ${detail}` : base);
        },
      });
  }

  /** i18n-Map (z. B. State-Label) für die aktuelle Sprache auflösen. */
  resolveLabel(map: I18nMap): string {
    return map[this.i18n.locale()] ?? map['de'] ?? Object.values(map)[0] ?? '';
  }

  // --- Einstellungen (Protokollant + Datum) / Löschen / Stimmabgabe / Beamer ----
  /** Einstellungs-Dialog öffnen (aus Toolbar oder Listen-Edit) + Roster laden. */
  openSettings(m: Meeting): void {
    this.settingsMeeting.set(m);
    this.settingsProtokollant.set(m.protokollantId ?? '');
    this.settingsDate.set(m.date ?? '');
    this.settingsTime.set(m.startTime ?? '');
    this.settingsRoster.set([]);
    this.api.listAttendance(m.id).subscribe({
      next: (rows) => {
        this.settingsRoster.set(rows);
        // Auswahl erst NACH dem Laden der Optionen (erneut) setzen — sonst snappt
        // das native <select> auf „niemand", weil die Option noch fehlte.
        this.settingsProtokollant.set(m.protokollantId ?? '');
      },
      error: () => this.settingsRoster.set([]),
    });
  }

  closeSettings(): void {
    this.settingsMeeting.set(null);
  }

  /** Protokollant + Datum/Zeit in einem Zug speichern (PATCH). */
  saveSettings(): void {
    const m = this.settingsMeeting();
    // Geschlossene Sitzung: komplett gesperrt (#15) — Backend lehnt ohnehin ab.
    if (!m || this.savingSettings() || this.settingsLocked()) return;
    this.savingSettings.set(true);
    // Protokollant nach Finalisierung gesperrt (#15) — Feld ist disabled, der
    // Wert wird gar nicht erst mitgesendet (Backend würde mit 409 ablehnen).
    this.api
      .patchMeeting(m.id, {
        ...(this.protokollantLocked()
          ? {}
          : { protokollantId: this.settingsProtokollant() || null }),
        date: this.settingsDate().trim() || null,
        startTime: this.settingsTime().trim() || null,
      })
      .subscribe({
        next: (updated) => {
          this.savingSettings.set(false);
          this.settingsMeeting.set(null);
          if (this.meeting()?.id === updated.id) this.meeting.set(updated);
          this.replaceInTimeline(updated);
          this.toast.success(this.i18n.translate('meetings.toast.settingsSaved'));
        },
        error: () => {
          this.savingSettings.set(false);
          this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
        },
      });
  }

  askDeleteMeeting(m: Meeting): void {
    this.confirmDeleteMeeting.set(m);
  }

  doDeleteMeeting(): void {
    const m = this.confirmDeleteMeeting();
    if (!m || this.deletingMeeting()) return;
    this.deletingMeeting.set(true);
    this.api.deleteMeeting(m.id).subscribe({
      next: () => {
        this.deletingMeeting.set(false);
        this.confirmDeleteMeeting.set(null);
        this.removeFromTimeline(m.id);
        this.toast.success(this.i18n.translate('meetings.toast.deleted'));
        // Aus der Detailansicht zurück zur Übersicht.
        if (this.meeting()?.id === m.id) void this.router.navigate(['/meetings']);
      },
      error: () => {
        this.deletingMeeting.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  /** Stimme abgeben (Protokollant/Mitglied mit `vote.cast`). */
  cast(voteId: Uuid, choice: string): void {
    if (this.casting()) return;
    this.casting.set(voteId);
    this.api.castBallot(voteId, choice).subscribe({
      next: () => {
        this.casting.set(null);
        this.myChoices.update((m) => ({ ...m, [voteId]: choice }));
        this.toast.success(this.i18n.translate('meetings.toast.voteCast'));
      },
      error: (err: unknown) => {
        this.casting.set(null);
        this.voteActionFailed(err);
      },
    });
  }

  /** Beschlussfrage (inkl. Stimmen) löschen — nur Vote-Verwalter. */
  deleteVote(voteId: Uuid): void {
    const m = this.meeting();
    if (!m || this.deletingVote()) return;
    this.deletingVote.set(voteId);
    this.api.deleteMeetingVote(m.id, voteId).subscribe({
      next: (updated) => {
        this.deletingVote.set(null);
        this.meeting.set(updated);
        this.toast.success(this.i18n.translate('meetings.toast.voteDeleted'));
      },
      error: () => {
        this.deletingVote.set(null);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  /** Auswahl-Optionen einer Abstimmung (Fallback: Zähl-Schlüssel). */
  voteOptionsFor(vote: MeetingVote): string[] {
    return vote.options.length ? vote.options : Object.keys(vote.counts ?? {});
  }

  /** TOP-Markdown für die Live-/Beamer-Ansicht rendern (sanitisiert via [innerHTML]). */
  renderBody(body: string): string {
    return renderMarkdown(body);
  }

  /** Beamer: aktuell offene Abstimmung, sonst die zuletzt geschlossene (persistiert). */
  readonly beamerVote = computed<MeetingVote | null>(() => {
    const votes = this.meeting()?.votes ?? [];
    return (
      votes.find((v) => v.status === 'open') ??
      [...votes].reverse().find((v) => v.status === 'closed') ??
      null
    );
  });

  // --- Live (WebSocket) ----------------------------------------------------
  private connectLive(meetingId: Uuid): void {
    this.viewers.set([]); // Stand der vorigen Sitzung verwerfen (#live-viewers)
    // Im Mock-Betrieb (FE-Dev/Harness) gibt es keinen WS-Server → kein Live-Kanal,
    // sonst scheitert der Handshake und verrauscht die Konsole.
    if (this.useMock) return;
    this.channel?.close();
    this.channel = this.ws.connectMeeting(meetingId);
    this.channel.messages$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => this.onLive(msg));
  }

  private onLive(msg: ServerMessage): void {
    const m = this.meeting();
    if (!m) return;
    switch (msg.type) {
      case 'meeting_state':
        this.meeting.set({
          ...m,
          status: (msg.status as Meeting['status']) ?? m.status,
          activeApplicationId: msg.activeApplicationId,
        });
        // TOP-Texte/Tagesordnung können sich (ohne Vote) geändert haben → neu laden,
        // damit Live-Follower den aktuellen Protokoll-Stand sehen (#live-refresh).
        this.loadAgenda(m.id);
        // Protokoll-Status kann geflippt sein (rendering → final/draft): der Worker
        // broadcastet meeting_state nach dem Hintergrund-Render (#async-finalize).
        // GET statt POST — Broadcast-Bursts dürfen das Write-Rate-Limit nicht
        // aufbrauchen (#429).
        if (this.canWrite() && this.protocol() && !this.protocol()!.isFinal) {
          this.api.getProtocol(m.id).subscribe({
            next: (proto) => this.applyProtocolUpdate(proto),
            error: () => {},
          });
        }
        break;
      case 'vote_opened':
        if (m.votes.some((v) => v.id === msg.voteId)) {
          this.patchVote(msg.voteId, { status: 'open', closesAt: msg.closesAt });
        } else {
          // Live geöffnete Abstimmung, die beim Laden noch nicht existierte (Follower).
          this.meeting.set({
            ...m,
            votes: [
              ...m.votes,
              {
                id: msg.voteId,
                applicationId: msg.applicationId ?? null,
                agendaItemId: msg.agendaItemId ?? null,
                title: null,
                question: msg.question ?? null,
                options: msg.options ?? [],
                status: 'open',
                result: null,
                counts: null,
                leading: null,
                closesAt: msg.closesAt,
                voted: 0,
                present: 0,
                revealed: false,
                failedReason: null,
              },
            ],
          });
        }
        break;
      case 'vote_tally':
        this.patchVote(msg.voteId, {
          counts: msg.counts,
          leading: msg.leading,
          voted: msg.cast ?? 0,
          present: msg.present ?? 0,
          revealed: msg.revealed ?? true,
        });
        break;
      case 'vote_closed':
        this.patchVote(msg.voteId, {
          status: 'closed',
          result: msg.result,
          counts: msg.counts,
          failedReason: msg.failedReason ?? null,
        });
        break;
      case 'viewers':
        // Wer hat die Sitzungs-Seite gerade offen (#live-viewers).
        this.viewers.set(msg.viewers);
        break;
      default:
        break;
    }
  }

  /** Ein einzelnes Vote im Sitzungs-State immutabel patchen. */
  private patchVote(voteId: Uuid, patch: Partial<MeetingVote>): void {
    const m = this.meeting();
    if (!m) return;
    this.meeting.set({
      ...m,
      votes: m.votes.map((v) => (v.id === voteId ? { ...v, ...patch } : v)),
    });
  }

  // --- Anzeige-Helfer ------------------------------------------------------
  statusVariant(status: Meeting['status']): BadgeVariant {
    return status === 'live' ? 'success' : status === 'closed' ? 'neutral' : 'info';
  }

  voteVariant(status: MeetingVote['status']): BadgeVariant {
    if (status === 'open') return 'success';
    if (status === 'closed') return 'neutral';
    return status === 'cancelled' ? 'danger' : 'warning';
  }

  /** Typsichere i18n-Keys aus dem dynamischen Status (strictTemplates). */
  statusKey(status: Meeting['status']): TranslationKey {
    return `meetings.status.${status}` as TranslationKey;
  }

  voteStatusKey(status: MeetingVote['status']): TranslationKey {
    return `meetings.voteStatus.${status}` as TranslationKey;
  }

  /** Übersetztes Label des Abstimmungs-Ergebnisses (Angenommen/Abgelehnt/…). */
  voteResultKey(result: string | null | undefined): TranslationKey {
    return `vote.result.${result ?? 'tie'}` as TranslationKey;
  }

  /** Ergebnis-Farbe: angenommen → grün, abgelehnt → rot, sonst neutral. */
  voteResultVariant(result: string | null | undefined): BadgeVariant {
    return result === 'passed' ? 'success' : result === 'rejected' ? 'danger' : 'neutral';
  }

  countEntries(vote: MeetingVote): { key: string; value: number }[] {
    return Object.entries(vote.counts ?? {}).map(([key, value]) => ({ key, value }));
  }
}
