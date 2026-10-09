import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router, RouterOutlet, type ParamMap } from '@angular/router';
import { EMPTY, of } from 'rxjs';
import { catchError, expand, filter, map, reduce } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Meeting, Uuid, VoteListItem, VoteStatus } from '@core/api/models';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
// By path, not through the `@shared/ui` barrel, so this lazy chunk takes only the blocks
// it uses.
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { ListDetailLayoutComponent } from '@shared/ui/list-detail/list-detail-layout.component';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StickyBarComponent } from '@shared/ui/sticky-bar/sticky-bar.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { meetingVoteStatus, type StatusView } from '@shared/status-kind.util';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { liveSearch } from '@shared/live-search';
import { mediaQuerySignal } from '../../../layout/media-query';
import { PageFrameService } from '../../../layout/page-frame.service';
import { LIVE_MAX_PAGES, LIVE_PAGE_LIMIT } from '../../../layout/rail-status.service';
import { groupByMonth } from '../../../pages/applications/applications.util';
import { VotingPageService } from './voting-page.service';
import { closedStatus } from '../election.util';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';

/** The status chip: the server default, the open votes, the ended votes, the drafts. */
export type VoteStatusFilter = '' | 'open' | 'ended' | 'draft';

const STATUS_QUERY: Record<Exclude<VoteStatusFilter, ''>, VoteStatus[]> = {
  open: ['open'],
  ended: ['closed', 'cancelled'],
  draft: ['draft'],
};

/** One page of the list. The open votes come first, so they fit on the first page. */
export const VOTE_PAGE = 30;

/** Live events in this window give one reload, not one each. */
export const VOTE_LIVE_DEBOUNCE = 300;

/** The largest page that `GET /votes` gives (`MAX_LIMIT`). A larger limit is a 422. */
export const VOTE_MAX_LIMIT = 200;

/** A vote that just opened in a followed meeting. */
interface FreshVote {
  id: Uuid;
  meetingId: Uuid;
}

/** One row as the template shows it. */
export interface VoteRow {
  item: VoteListItem;
  /** The month key of `groupByMonth`: the end of an ended vote, else its start. */
  createdAt: string;
  title: string;
  status: StatusView;
  /** "TOP 3 · 34. Sitzung …", else the gremium. */
  where: string | null;
  /** "Abgestimmt", "Stimme offen" or nothing. */
  ballot: 'cast' | 'pending' | null;
  /** "seit 18:48", "bis 07.10., 22:00", "12.06.2026". */
  when: string | null;
  /** The exact moment, for the tooltip of `when`. */
  whenTitle: string | null;
}

/** A group of rows: the open votes, the drafts, or one month of the ended votes. */
export interface VoteGroup {
  key: string;
  label: string;
  rows: VoteRow[];
}

/**
 * "Abstimmungen" (`/voting`, boards Arbeit-Abstimmungen and Telefon-Abstimmen): the votes
 * of the person as a list beside the open vote, like the applications and the tasks.
 *
 * - Left: `GET /votes`, the open votes first ("Offen"), then the drafts ("Entwürfe", only
 *   with the status chip) and the ended votes by month. A row shows the question, the
 *   status or the result, the meeting with the agenda item (else the gremium), the own
 *   ballot ("Abgestimmt" / "Stimme offen") and the time. The search and the chips
 *   (Status, Gremium) live in the query params, so a filtered list is a link.
 * - Right: the child route `/voting/:id` with the vote (`VoteCastComponent`): the
 *   two-step ballot, the proxy ballot, the turnout, the result and the manage actions.
 *   After a cast the detail stays on the vote and the row reads "Abgestimmt".
 * - Live: the page follows the running meetings over the WebSocket. A vote that opens,
 *   closes or is cancelled reloads the list. The page opens a vote that just opened when
 *   no vote is open in the detail (also on a phone, from the list), or when the detail
 *   shows an ended vote of the same meeting. A vote that the channel replays on a
 *   connect was open before, so it does not open by itself. On the first load side by
 *   side the page opens the first open vote, as the board shows it.
 * - One pane at a time (narrow, phone): the list, then the vote with a way back.
 */
@Component({
  selector: 'app-voting',
  // A pane page (styles.scss): side by side the panes fill the free height and scroll by
  // themselves.
  host: { '[class.pane-page]': 'split()' },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageHeaderComponent,
    RouterOutlet,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    ListDetailLayoutComponent,
    ListItemComponent,
    SearchPillComponent,
    SkeletonComponent,
    StickyBarComponent,
    StatusTextComponent,
    ScrollFadeDirective,
  ],
  providers: [VotingPageService],
  templateUrl: './voting.component.html',
  styleUrl: './voting.component.scss',
})
export class VotingComponent implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly page = inject(VotingPageService);
  private readonly frame = inject(PageFrameService);

  readonly phone = mediaQuerySignal(MEDIA.phone);

  /** The list-detail layout, for its split state. */
  private readonly layout = viewChild(ListDetailLayoutComponent);
  /** The list and the detail sit side by side. */
  readonly split = computed(() => this.layout()?.collapsed() === false);

  /** The id of the vote in the detail pane, from the child route. */
  readonly selectedId = signal<Uuid | null>(null);

  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly error = signal(false);
  readonly items = signal<VoteListItem[]>([]);
  readonly total = signal(0);
  /** Fetch sequence number. The handler drops a late answer of an older request. */
  private fetchSeq = 0;
  /** The first open vote opens by itself once, on the first load side by side. */
  private autoOpened = false;

  // Filters, from the query params.
  readonly q = signal('');
  /**
   * The search field: it searches while the user types (`liveSearch`, debounced, from
   * two characters), Enter searches at once, Escape and × clear it. A search writes `q`
   * into the URL; the list loads from there.
   */
  readonly search = liveSearch({
    run: (query) => {
      this.navigate({ q: query || null });
    },
  });
  readonly statusFilter = signal<VoteStatusFilter>('');
  readonly gremiumId = signal('');
  readonly activeFilterCount = computed(
    () => (this.q() ? 1 : 0) + (this.statusFilter() ? 1 : 0) + (this.gremiumId() ? 1 : 0),
  );

  /** A manager sees the drafts of the votes. */
  private readonly canManage = computed(
    () =>
      this.auth.isAdmin() ||
      this.auth.canInAnyGremium('vote.manage') ||
      this.auth.canInAnyGremium('session.manage'),
  );

  readonly statusOptions = computed<FilterSelectOption[]>(() => {
    const opts: FilterSelectOption[] = [
      { value: '', label: this.i18n.translate('voting.list.filter.all') },
      { value: 'open', label: this.i18n.translate('voting.list.filter.open') },
      { value: 'ended', label: this.i18n.translate('voting.list.filter.ended') },
    ];
    if (this.canManage()) {
      opts.push({ value: 'draft', label: this.i18n.translate('voting.list.filter.draft') });
    }
    return opts;
  });
  readonly statusChipLabel = computed(() => {
    const value = this.statusFilter();
    if (!value) return this.i18n.translate('voting.list.filter.status');
    return this.statusOptions().find((o) => o.value === value)?.label ?? value;
  });

  /** The gremien of the person, plus the gremien of the loaded rows. */
  private readonly seenGremien = signal<ReadonlyMap<string, string>>(new Map());
  readonly gremiumOptions = computed<FilterSelectOption[]>(() => {
    const names = new Map<string, string>();
    for (const g of this.auth.gremien()) names.set(g.id, g.name);
    for (const [id, name] of this.seenGremien()) if (!names.has(id)) names.set(id, name);
    const sorted = [...names].sort((a, b) => a[1].localeCompare(b[1], this.i18n.locale()));
    return [
      { value: '', label: this.i18n.translate('voting.list.filter.all') },
      ...sorted.map(([value, label]) => ({ value, label })),
    ];
  });
  /** The chip shows only when there is a choice, or while it is set. */
  readonly showGremiumChip = computed(
    () => this.gremiumOptions().length > 2 || this.gremiumId() !== '',
  );
  readonly gremiumChipLabel = computed(() => {
    const id = this.gremiumId();
    if (!id) return this.i18n.translate('voting.list.filter.gremium');
    return this.gremiumOptions().find((o) => o.value === id)?.label ?? id;
  });

  readonly hasMore = computed(() => this.items().length < this.total());
  /** The open votes among the loaded rows. They come first, so the count is exact. */
  readonly openCount = computed(() => this.items().filter((i) => i.status === 'open').length);

  readonly rows = computed<VoteRow[]>(() => this.items().map((item) => this.toRow(item)));

  /** "Offen", "Entwürfe", then the ended votes by month. */
  readonly groups = computed<VoteGroup[]>(() => {
    const rows = this.rows();
    const out: VoteGroup[] = [];
    const open = rows.filter((r) => r.item.status === 'open');
    const drafts = rows.filter((r) => r.item.status === 'draft');
    const ended = rows.filter((r) => r.item.status === 'closed' || r.item.status === 'cancelled');
    if (open.length) {
      out.push({ key: 'open', label: this.i18n.translate('voting.list.group.open'), rows: open });
    }
    if (drafts.length) {
      out.push({ key: 'draft', label: this.i18n.translate('voting.list.group.draft'), rows: drafts });
    }
    for (const g of groupByMonth(ended, this.i18n.locale())) {
      out.push({ key: `m-${g.key}`, label: g.label, rows: g.items });
    }
    return out;
  });

  constructor() {
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.readFilters(pm);
      this.reload();
    });

    this.readSelection();
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.readSelection());

    // The detail cast a ballot or deleted the vote: the row follows.
    this.page.changes$.pipe(takeUntilDestroyed()).subscribe((change) => {
      if (change.kind === 'deleted') {
        const before = this.items().length;
        this.items.update((cur) => cur.filter((i) => i.id !== change.id));
        if (this.items().length < before) this.total.update((t) => Math.max(0, t - 1));
        return;
      }
      this.refresh();
    });

    effect(() => this.page.split.set(this.split()));
    effect(() => this.frame.fill.set(this.split()));

    // The first open vote opens by itself on the first load side by side (the board shows
    // the vote at once). One pane at a time the list comes first.
    effect(() => {
      const split = this.split();
      const loading = this.loading();
      const first = this.items()[0];
      untracked(() => {
        if (this.autoOpened || loading || !split) return;
        this.autoOpened = true;
        if (!this.selectedId() && first?.status === 'open') this.openRow(first.id, true);
      });
    });

    this.followLive();
  }

  ngOnDestroy(): void {
    this.frame.fill.set(false);
    if (this.liveTimer) clearTimeout(this.liveTimer);
  }

  // --- navigation ---------------------------------------------------------

  /** "Zur Liste" and the back of the phone header: close the vote, keep the filters. */
  closeDetail(): void {
    void this.router.navigate(['/voting'], { queryParamsHandling: 'preserve' });
  }

  private openRow(id: Uuid, replace = false): void {
    void this.router.navigate(['/voting', id], {
      queryParamsHandling: 'preserve',
      replaceUrl: replace,
    });
  }

  private readSelection(): void {
    this.selectedId.set(this.route.snapshot.firstChild?.paramMap.get('id') ?? null);
  }

  // --- filters ------------------------------------------------------------

  setStatus(value: string): void {
    this.navigate({ status: value || null });
  }

  setGremium(value: string): void {
    this.navigate({ gremium: value || null });
  }

  reset(): void {
    this.search.sync('');
    this.navigate({ q: null, status: null, gremium: null });
  }

  private readFilters(pm: ParamMap): void {
    this.q.set((pm.get('q') ?? '').trim());
    this.search.sync(this.q());
    const status = pm.get('status') ?? '';
    // Only a manager has the draft chip. A link with `status=draft` shows the default
    // list to anybody else.
    const known = status in STATUS_QUERY && (status !== 'draft' || this.canManage());
    this.statusFilter.set(known ? (status as VoteStatusFilter) : '');
    this.gremiumId.set(pm.get('gremium') ?? '');
  }

  private navigate(queryParams: Record<string, string | null>): void {
    void this.router.navigate([], {
      relativeTo: this.route.firstChild ?? this.route,
      queryParams,
      queryParamsHandling: 'merge',
    });
  }

  // --- loading ------------------------------------------------------------

  /** Load page 0 after a filter change. The rows stay until the new ones arrive. */
  private reload(): void {
    this.loading.set(this.items().length === 0);
    this.error.set(false);
    this.fetch('initial', 0, VOTE_PAGE);
  }

  /**
   * Load the loaded rows again (a ballot, a live event). A failure keeps the rows. The
   * server gives at most `VOTE_MAX_LIMIT` rows at a time, so after many "Mehr laden" the
   * list shrinks to that many rows.
   */
  refresh(): void {
    if (this.loading() || this.items().length === 0) {
      this.reload();
      return;
    }
    const limit = Math.min(VOTE_MAX_LIMIT, Math.max(VOTE_PAGE, this.items().length));
    this.fetch('refresh', 0, limit);
  }

  loadMore(): void {
    if (this.loadingMore() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch('more', this.items().length, VOTE_PAGE);
  }

  private fetch(mode: 'initial' | 'refresh' | 'more', offset: number, limit: number): void {
    const seq = ++this.fetchSeq;
    const status = this.statusFilter();
    this.api
      .listVotes({
        status: status ? STATUS_QUERY[status] : undefined,
        gremiumId: this.gremiumId() || undefined,
        q: this.q() || undefined,
        limit,
        offset,
      })
      .subscribe({
        next: (page) => {
          if (seq !== this.fetchSeq) return;
          this.total.set(page.total);
          this.items.update((cur) => (mode === 'more' ? [...cur, ...page.items] : page.items));
          this.collectGremien(page.items);
          this.followOpen(page.items);
          this.loading.set(false);
          this.loadingMore.set(false);
        },
        error: () => {
          if (seq !== this.fetchSeq) return;
          if (mode === 'initial') {
            this.items.set([]);
            this.total.set(0);
            this.error.set(true);
          }
          this.loading.set(false);
          this.loadingMore.set(false);
        },
      });
  }

  private collectGremien(items: VoteListItem[]): void {
    const names = new Map(this.page.gremiumNames());
    for (const item of items) if (item.gremiumName) names.set(item.id, item.gremiumName);
    this.page.gremiumNames.set(names);
    const next = new Map(this.seenGremien());
    let changed = false;
    for (const item of items) {
      if (item.gremiumId && item.gremiumName && !next.has(item.gremiumId)) {
        next.set(item.gremiumId, item.gremiumName);
        changed = true;
      }
    }
    if (changed) this.seenGremien.set(next);
  }

  // --- live ---------------------------------------------------------------

  private liveTimer: ReturnType<typeof setTimeout> | null = null;

  /**
   * Follow the running meetings: the live meetings of the upcoming timeline (as the rail
   * finds them) and the meetings of the open votes in the list. A vote that opens,
   * closes or is cancelled in one of them reloads the list, and a vote that just opened
   * can open in the detail (`openFresh`).
   */
  private followLive(): void {
    const page = (cursor: string | null) =>
      this.api.listMeetingsTimeline({ direction: 'upcoming', limit: LIVE_PAGE_LIMIT, cursor });
    page(null)
      .pipe(
        expand((p, i) => (p.nextCursor && i + 1 < LIVE_MAX_PAGES ? page(p.nextCursor) : EMPTY)),
        map((p) => p.items.filter((m) => m.status === 'live')),
        reduce((all, items) => [...all, ...items], [] as Meeting[]),
        catchError(() => of([] as Meeting[])),
        takeUntilDestroyed(),
      )
      .subscribe((running) => {
        for (const m of running) this.page.follow(m.id);
      });

    let last: string | null = null;
    effect(() => {
      // The open vote and the last result of every followed meeting. A change of this
      // signature is a vote that opened, closed or was cancelled.
      const sessions = [...this.page.sessions()];
      const opened = sessions.map(([, s]) => s.openVote());
      const signature = sessions
        .map(([, s], i) => `${opened[i]?.voteId ?? '-'}:${s.result()?.voteId ?? '-'}`)
        .join('|');
      untracked(() => {
        if (last === null) {
          last = signature;
          return;
        }
        if (signature === last) return;
        const known = new Set(last.split('|').map((part) => part.split(':')[0]));
        last = signature;
        // A channel replays the open vote on each connect and marks it as a replay: that
        // vote was open before, so it did not just open. The flag comes from the channel,
        // not from the rows, so a filter that hides the vote (status "Beendet", another
        // gremium, a search) does not make it new. Before the first rows arrive, nothing
        // is new: the first load opens the first open vote itself.
        const at = this.loading()
          ? -1
          : opened.findIndex((msg) => !!msg && msg.replay !== true && !known.has(msg.voteId));
        this.onLive(at < 0 ? null : { id: opened[at]!.voteId, meetingId: sessions[at]![0] });
      });
    });
  }

  private onLive(fresh: FreshVote | null): void {
    if (this.liveTimer) clearTimeout(this.liveTimer);
    this.liveTimer = setTimeout(() => {
      this.liveTimer = null;
      this.refresh();
      if (fresh) this.openFresh(fresh);
    }, VOTE_LIVE_DEBOUNCE);
  }

  /**
   * A vote just opened in a followed meeting. A member in the room must see it at once,
   * as on the former live page:
   *
   * - No vote in the detail (the list, also on a phone): open the new vote.
   * - The detail shows an ended vote of the same meeting (the vote before): replace it
   *   with the new vote, so the way back still goes to the list.
   * - Any other vote (an open vote, a draft, a vote of another meeting) stays.
   */
  private openFresh(fresh: FreshVote): void {
    const selected = this.selectedId();
    if (!selected) {
      this.openRow(fresh.id);
      return;
    }
    if (selected === fresh.id) return;
    const shown = this.page.shown();
    const vote =
      shown?.id === selected ? shown : this.items().find((i) => i.id === selected);
    if (!vote || vote.meetingId !== fresh.meetingId) return;
    // The close of the shown vote and the open of the next can come in one burst; the
    // detail may not have read the result yet. The channel already has it.
    const closed = this.page.sessions().get(fresh.meetingId)?.result()?.voteId === selected;
    if (vote.status === 'closed' || vote.status === 'cancelled' || closed) {
      this.openRow(fresh.id, true);
    }
  }

  /** Follow the meeting of every open meeting vote of the list. */
  private followOpen(items: VoteListItem[]): void {
    for (const item of items) {
      if (item.status === 'open' && item.meetingId) this.page.follow(item.meetingId);
    }
  }

  // --- rows ---------------------------------------------------------------

  private toRow(item: VoteListItem): VoteRow {
    const ended = item.status === 'closed' || item.status === 'cancelled';
    const status =
      item.status === 'closed' && item.result ? closedStatus(item.kind, item.result) : this.statusOf(item.status);
    let where: string | null = item.gremiumName;
    if (item.meetingTitle) {
      where =
        item.agendaPosition === null
          ? item.meetingTitle
          : this.i18n.translate('voting.panel.wherePhone', {
              meeting: item.meetingTitle,
              n: item.agendaPosition,
            });
    }
    let ballot: VoteRow['ballot'] = null;
    if (item.myBallot.cast) ballot = 'cast';
    else if (item.status === 'open' && item.canCast) ballot = 'pending';
    const [when, whenTitle] = this.whenOf(item);
    return {
      item,
      createdAt: (ended ? (item.closedAt ?? item.openedAt) : item.openedAt) ?? item.createdAt,
      title: item.question?.trim() || this.i18n.translate('meetings.vote.untitled'),
      status,
      where,
      ballot,
      when,
      whenTitle,
    };
  }

  private statusOf(status: VoteStatus): StatusView {
    if (status === 'draft') return { kind: 'neutral', key: 'voting.list.status.draft' };
    return meetingVoteStatus(status);
  }

  /**
   * The time of a row. Open: "bis <end>" when the vote has a planned end, else "seit
   * <start>". Ended: the day it ended. Draft: the day it was made. A time of today shows
   * only the clock.
   */
  private whenOf(item: VoteListItem): [string | null, string | null] {
    let key: TranslationKey | null = null;
    let at: string | null = null;
    if (item.status === 'open') {
      if (item.closesAt) {
        key = 'voting.list.until';
        at = item.closesAt;
      } else if (item.openedAt) {
        key = 'voting.list.since';
        at = item.openedAt;
      }
    } else if (item.status === 'draft') {
      at = item.createdAt;
    } else {
      at = item.closedAt ?? item.openedAt;
    }
    if (!at) return [null, null];
    const date = new Date(at);
    if (Number.isNaN(date.getTime())) return [null, null];
    const locale = this.i18n.formatLocale();
    const today = new Date(Date.now()).toDateString() === date.toDateString();
    const text = today
      ? new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(date)
      : new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit', year: 'numeric' }).format(date);
    const exact = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(
      date,
    );
    return [key ? this.i18n.translate(key, { time: text }) : text, exact];
  }
}
