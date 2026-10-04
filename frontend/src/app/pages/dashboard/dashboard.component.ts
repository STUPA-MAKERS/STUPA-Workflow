import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  ApplicationListItem,
  ApplicationType,
  IsoDateTime,
  Meeting,
  Uuid,
} from '@core/api/models';
import { BadgeComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import {
  AvatarComponent,
  DateBlockComponent,
  ListItemComponent,
  PageHeaderComponent,
  SearchPillComponent,
  SegBarComponent,
  SideSheetComponent,
  SkeletonComponent,
  StatusTextComponent,
  flowColorKind,
} from '@shared/ui';
import { shortTime } from '../../features/meetings/meetings-display.util';
import { CommandPaletteService } from '../../features/search/command-palette.service';
import { AccountMenuComponent } from '../../layout/account-menu/account-menu.component';
import { mediaQuerySignal } from '../../layout/media-query';

/** Rows per section on a wide or narrow screen (board Main). */
const ROWS = 4;
/** Rows on a phone (board Telefon-Start): the live meeting and the next one, three tasks. */
const PHONE_MEETINGS = 2;
const PHONE_ROWS = 3;

/** A live or planned meeting, ready for the template. */
export interface SessionRow {
  meeting: Meeting;
  live: boolean;
  /** "Studierendenparlament · seit 18:04" or "Finanzausschuss · Fr, 17:30". */
  sub: string;
  /** The current agenda item of a live meeting, or null. */
  now: { position: number; title: string; count: number } | null;
}

/**
 * The start page of a signed-in member (boards Main, Schmal-Start and Telefon-Start).
 *
 * At the top: the search pill and the one action taken from here, "Antrag stellen".
 * Below the greeting four sections. On a wide screen they sit in two columns that fill the
 * width; below 1200px they stack.
 *
 * - "Laufende & anstehende Sitzungen": live meetings first, then planned ones by date. A
 *   live meeting shows when it started and the agenda item it handles now.
 * - "Vertretung": the meeting-bound delegations of the user for a meeting that is not over.
 * - "Offene Aufgaben": the first rows of GET /applications/tasks.
 * - "Meine Anträge": the first rows of the own applications (`mine=true`).
 *
 * On a phone the page gets a compact head (search and account) and a floating "Antrag"
 * button, and the sections show fewer rows.
 *
 * Only the applications list shows the global loading overlay (the first paint). The other
 * requests run beside it with `skipLoading`, and each section has its own state.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    IconComponent,
    TranslatePipe,
    BadgeComponent,
    AvatarComponent,
    DateBlockComponent,
    ListItemComponent,
    PageHeaderComponent,
    SearchPillComponent,
    SegBarComponent,
    SideSheetComponent,
    SkeletonComponent,
    StatusTextComponent,
    AccountMenuComponent,
  ],
  host: {
    '[class.dash--phone]': 'phone()',
  },
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent {
  readonly auth = inject(AuthService);
  /** The search pill at the top opens the global search. */
  protected readonly palette = inject(CommandPaletteService);
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly delegationsApi = inject(DelegationsApiService);

  /** Phone width (<= 768px): compact head, floating apply button, fewer rows. */
  readonly phone = mediaQuerySignal(MEDIA.phone);
  /** The account sheet of the compact phone head. */
  readonly accountOpen = signal(false);

  protected readonly flowColorKind = flowColorKind;

  /** "My applications": only the applications the user owns. `mine=true` forces the
   *  owner filter, even for a principal with `application.read`. Without it, the card
   *  would show every application to an entitled user. */
  private readonly applications = toSignal(
    this.api.listApplications({ mine: true, limit: ROWS }).pipe(catchError(() => of(null))),
    { initialValue: undefined },
  );

  /** "Open tasks": real open decisions (GET /applications/tasks). `null` = failed. */
  private readonly tasks = toSignal(
    this.api.listTasks().pipe(catchError(() => of(null))),
    { initialValue: undefined },
  );

  private readonly types = toSignal(
    this.api.applicationTypes({ quiet: true }).pipe(catchError(() => of([] as ApplicationType[]))),
    { initialValue: [] as ApplicationType[] },
  );
  private readonly typeName = computed(() => {
    const map = new Map(this.types().map((t) => [t.id, t.name]));
    return (id: Uuid): string => map.get(id) ?? id;
  });

  private readonly meetings = toSignal(
    this.api.listMeetings().pipe(catchError(() => of([] as Meeting[]))),
    { initialValue: [] as Meeting[] },
  );

  private readonly delegationsRaw = toSignal(
    this.delegationsApi.list().pipe(catchError(() => of([] as Delegation[]))),
    { initialValue: [] as Delegation[] },
  );

  // ---------------------------------------------------------------- head

  /** The first word of the display name: "Willkommen, Mara". */
  readonly firstName = computed(() => {
    const name = this.auth.displayName().trim();
    return name.split(/\s+/)[0] || name;
  });

  /** The gremien of the user, as one line under the greeting. */
  readonly gremienLine = computed(() =>
    this.auth
      .gremien()
      .map((g) => g.name)
      .join(' · '),
  );

  // ---------------------------------------------------------------- applications

  /** `true` while the applications endpoint has not responded yet. */
  readonly loading = computed(() => this.applications() === undefined);
  /** `true` if the applications endpoint failed. */
  readonly error = computed(() => this.applications() === null);
  readonly total = computed(() => this.applications()?.total ?? 0);

  private readonly rowCap = computed(() => (this.phone() ? PHONE_ROWS : ROWS));

  readonly applicationRows = computed(() =>
    (this.applications()?.items ?? []).slice(0, this.rowCap()),
  );

  /** The application panels need this permission. */
  readonly canReadApplications = computed(() => this.auth.canAny('application.read'));

  // ---------------------------------------------------------------- tasks

  readonly tasksLoading = computed(() => this.tasks() === undefined);
  readonly tasksError = computed(() => this.tasks() === null);
  readonly openTasks = computed<ApplicationListItem[]>(() => this.tasks() ?? []);
  readonly taskRows = computed(() => this.openTasks().slice(0, this.rowCap()));

  // ---------------------------------------------------------------- meetings

  /** Live and planned meetings: live first, then planned ones by date. */
  private readonly activeMeetings = computed<Meeting[]>(() => {
    const rank = (m: Meeting): number => (m.status === 'live' ? 0 : m.status === 'planned' ? 1 : 2);
    return this.meetings()
      .filter((m) => m.status !== 'closed')
      .slice()
      .sort((a, b) => rank(a) - rank(b) || (a.date ?? '').localeCompare(b.date ?? ''));
  });

  /** How many live and planned meetings there are, also those not shown. */
  readonly sessionCount = computed(() => this.activeMeetings().length);

  readonly sessions = computed<SessionRow[]>(() =>
    this.activeMeetings()
      .slice(0, this.phone() ? PHONE_MEETINGS : ROWS)
      .map((m) => this.sessionRow(m)),
  );

  private sessionRow(m: Meeting): SessionRow {
    const live = m.status === 'live';
    const when = live ? this.startedLabel(m) : this.plannedLabel(m);
    const sub = [m.gremiumName, when].filter((s): s is string => !!s).join(' · ');
    const item = m.currentAgendaItem;
    const count = m.agendaItemCount ?? 0;
    const now =
      live && item && count > 0
        ? { position: item.position, title: item.title ?? '', count }
        : null;
    return { meeting: m, live, sub, now };
  }

  /** "seit 18:04": the real start, else the planned start of an older meeting. */
  private startedLabel(m: Meeting): string | null {
    const time = m.startedAt ? this.clock(m.startedAt) : shortTime(m.startTime);
    return time ? this.i18n.translate('dashboard.sessions.since', { time }) : null;
  }

  /** "Fr, 17:30": the weekday of the date and the planned start. */
  private plannedLabel(m: Meeting): string | null {
    const day = this.weekday(m.date);
    const time = shortTime(m.startTime);
    return [day, time].filter((s) => !!s).join(', ') || null;
  }

  /** The short weekday of a `YYYY-MM-DD` date in the local calendar, without a dot. */
  private weekday(date: string | null): string {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date ?? '');
    if (!match) return '';
    const d = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return d
      .toLocaleDateString(this.i18n.formatLocale(), { weekday: 'short' })
      .replace(/\.$/, '');
  }

  /** The local time of an instant as HH:MM. */
  private clock(at: IsoDateTime): string {
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString(this.i18n.formatLocale(), { hour: '2-digit', minute: '2-digit' });
  }

  // ---------------------------------------------------------------- delegations

  /**
   * The delegations of the user for a meeting that is not over.
   *
   * GET /delegations without a meeting gives the own outgoing and incoming delegations of
   * all meetings (an admin gets every delegation; the rows of other persons have no
   * direction and stay out). The rows carry no meeting status: a meeting in the list of
   * live and planned meetings counts, a closed one does not, and a meeting the list does
   * not hold counts while its date is today or later.
   */
  readonly delegations = computed<Delegation[]>(() => {
    const active = new Set(this.activeMeetings().map((m) => m.id));
    const closed = new Set(
      this.meetings()
        .filter((m) => m.status === 'closed')
        .map((m) => m.id),
    );
    const today = this.today();
    return this.delegationsRaw()
      .filter((d) => d.direction !== null && !closed.has(d.meetingId))
      .filter((d) => active.has(d.meetingId) || (!!d.meetingDate && d.meetingDate >= today))
      .slice(0, ROWS);
  });

  /** Outgoing means another person represents the user. The server sets the direction. */
  isOutgoing(d: Delegation): boolean {
    return d.direction === 'outgoing';
  }

  /** The other person of a delegation: the delegate or the delegator. */
  otherName(d: Delegation): string {
    return (this.isOutgoing(d) ? d.delegateName : d.delegatorName) || '?';
  }

  /** "12. Sitzung des Finanzausschusses, 02.10.2026". */
  delegationSub(d: Delegation): string {
    const date = d.meetingDate ? this.longDay(d.meetingDate) : '';
    return [d.meetingTitle, date].filter((s) => !!s).join(', ');
  }

  // ---------------------------------------------------------------- rows

  name(item: ApplicationListItem): string {
    return this.typeName()(item.typeId);
  }

  titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.typeName()(item.typeId);
  }

  /** The type in the sub line, only when the title is not already the type. */
  typeOf(item: ApplicationListItem): string | null {
    return item.title?.trim() ? this.name(item) : null;
  }

  /** The date of an own application: the last status change, else the last change. */
  dateOf(item: ApplicationListItem): IsoDateTime | null {
    return item.stateSince ?? item.updatedAt ?? null;
  }

  /** "28.08." in the current year, "28.08.2025" before. */
  shortDay(at: IsoDateTime | null): string {
    if (!at) return '';
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return '';
    const sameYear = d.getFullYear() === new Date().getFullYear();
    return d.toLocaleDateString(this.i18n.formatLocale(), {
      day: '2-digit',
      month: '2-digit',
      ...(sameYear ? {} : { year: 'numeric' }),
    });
  }

  /** "02.10.2026" for a `YYYY-MM-DD` date. */
  private longDay(date: string): string {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date);
    if (!match) return date;
    const d = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return d.toLocaleDateString(this.i18n.formatLocale(), {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  }

  /** Today as `YYYY-MM-DD` in the local calendar. */
  private today(): string {
    const d = new Date();
    const pad = (n: number): string => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  // ---------------------------------------------------------------- layout

  /** The start column holds meetings and delegations. Without both, one column remains. */
  readonly hasStartColumn = computed(
    () => this.sessions().length > 0 || this.delegations().length > 0,
  );

  openAccount(): void {
    this.accountOpen.set(true);
  }

  closeAccount(): void {
    this.accountOpen.set(false);
  }
}
