import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';
import type { GremiumOverview } from '@core/api/gremien.service';
import type { Team, TeamDetail } from '@core/api/teams.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { searchPlaceholder } from '@shared/util/search-placeholder';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
  ListDetailLayoutComponent,
  ListGroupComponent,
  ListItemComponent,
  MEDIA,
  mediaQuery,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  SearchPillComponent,
  SkeletonComponent,
  StickyBarComponent,
  PageHeaderComponent,
} from '@stupa-makers/ui-kit';
import { injectListDetailPage } from '@stupa-makers/ui-kit/shell';
import { CalendarSubscribeComponent } from '../../meetings/calendar-subscribe/calendar-subscribe.component';
import { GremienApiService } from '@core/api/gremien.service';
import { prefetchDetails } from '@core/cache/detail-prefetch';
import { GremienStore } from '../gremien.store';
import { localized, teamTree } from '../gremien.util';
import { weekdayDate } from '@shared/date-format';
import { GremiumLogoComponent } from '../gremium-logo/gremium-logo.component';
import { TeamNameDialogComponent } from '../team-name-dialog/team-name-dialog.component';
import { RowChevronComponent } from '@shared/ui/row-chevron/row-chevron.component';
import { PullRefreshDirective } from '@shared/ui/pull-refresh/pull-refresh.directive';
import { isRefreshItem, refreshMenuSection, reloadLikePull } from '@shared/ui/pull-refresh/refresh-menu';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import { IMAGE_PRELOADER } from '@shared/util/preload-images';

/** The permission that shows every gremium, also without a membership. */
export const GREMIUM_VIEW_ALL = 'gremium.view_all';

/** The chip "Anzeigen": the own gremien, or every visible gremium. */
export type GremienScope = 'mine' | 'all';

/** One row of the list, ready for the template: a team, with its Gremium if inherent. */
export interface GremiumRow {
  readonly team: Team;
  /** The Gremium of an inherent team, else null. */
  readonly item: GremiumOverview | null;
  /** The level under the shown parent team (spec 003072). */
  readonly depth: number;
  readonly sub: string;
  /** `live`, a date ("Di, 20.10."), or `none`. */
  readonly next:
    | { readonly kind: 'live' }
    | { readonly kind: 'date'; readonly text: string; readonly title: string }
    | { readonly kind: 'none' };
}

/**
 * The tab "Teams" (`/teams`, spec 003072): a list/detail pane page like the votes.
 *
 * - Left: the title with the calendar subscription and "Team anlegen" (`team.create`), the
 *   search and, with `gremium.view_all`, the chip "Anzeigen: Meine Teams | Alle Teams". Then
 *   the groups "Meine Teams" and "Weitere Teams", each sub-team right under its parent,
 *   without a step in: its row names the parent ("↳ AStA", spec 003075 of the kit). The row of an inherent team shows the logo of its Gremium, the role and the number
 *   of members, and the next meeting ("Läuft", a date or "keine geplant"). The row of
 *   another team shows the own role in it.
 * - Right: the child route `/teams/:id` with the open team (`GremiumDetailComponent`).
 *   The page opens no gremium by itself (§ui-kit:000664).
 * - One pane at a time (narrow, phone): the list, then the gremium with a way back.
 *
 * The search filters the loaded list in the browser: the list is short and complete.
 *
 * Side by side it is a pane page (`styles.scss`): the panes fill the free height.
 */
@Component({
  selector: 'app-gremien',
  host: { '[class.pane-page]': 'split()' },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PullRefreshDirective,
    RowChevronComponent,
    LoadErrorComponent,
    NgTemplateOutlet,
    RouterOutlet,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    ListDetailLayoutComponent,
    ListGroupComponent,
    ListItemComponent,
    PageHeaderComponent,
    RowMenuComponent,
    SearchPillComponent,
    SkeletonComponent,
    StickyBarComponent,
    ScrollFadeDirective,
    CalendarSubscribeComponent,
    GremiumLogoComponent,
    TeamNameDialogComponent,
  ],
  providers: [GremienStore],
  templateUrl: './gremien.component.html',
  styleUrl: './gremien.component.scss',
})
export class GremienComponent {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  protected readonly store = inject(GremienStore);
  private readonly preload = inject(IMAGE_PRELOADER);

  /**
   * The logos of the first answer are still loading (spec 001280): the skeleton stays until
   * each logo has loaded or failed, at most `IMAGE_PRELOAD_LIMIT_MS`. A refresh does not wait.
   */
  private readonly logosPending = signal(true);
  private logosStarted = false;

  /** The skeleton shows: the list or the logos of its first answer are still loading. */
  readonly showSkeleton = computed(() => this.store.loading() || this.logosPending());

  readonly phone = mediaQuery(MEDIA.phone);

  private readonly layout = viewChild(ListDetailLayoutComponent);
  private readonly listDetail = injectListDetailPage(this.layout);
  /** The list and the detail sit side by side. */
  readonly split = this.listDetail.split;

  /** The gremium of the child route `:id`. */
  readonly selectedId = this.listDetail.selectedId;

  /** The Gremium of an old link `/committees/:id` (spec 003072). */
  private readonly gremiumParam = toSignal(
    this.route.queryParamMap.pipe(map((q) => q.get('gremium'))),
    { initialValue: this.route.snapshot.queryParamMap.get('gremium') },
  );

  readonly query = signal('');
  /** The chip "Anzeigen" shows only with `gremium.view_all`. */
  readonly viewAll = computed(() => this.auth.can(GREMIUM_VIEW_ALL));
  readonly scope = signal<GremienScope>('all');

  readonly scopeOptions = computed<FilterSelectOption[]>(() => [
    { value: 'mine', label: this.i18n.translate('gremien.list.showMine') },
    { value: 'all', label: this.i18n.translate('gremien.list.showAll') },
  ]);

  /** A team that the list shows besides the own ones: with view_all and the chip "Alle". */
  private readonly showsOthers = computed(() => this.viewAll() && this.scope() === 'all');

  /** The teams that match the search, in the order of the server (by name). */
  private readonly matching = computed(() => {
    const locale = this.i18n.locale();
    const q = this.query().trim().toLocaleLowerCase(locale);
    const teams = this.store.teams();
    if (!q) return teams;
    return teams.filter(
      (t) =>
        t.name.toLocaleLowerCase(locale).includes(q) ||
        (this.store.find(t.gremiumId)?.slug.toLocaleLowerCase().includes(q) ?? false),
    );
  });

  readonly mine = computed(() =>
    teamTree(this.matching().filter((t) => t.isMember)).map((n) => this.toRow(n.team, n.depth)),
  );
  readonly others = computed(() =>
    this.showsOthers()
      ? teamTree(this.matching().filter((t) => !t.isMember)).map((n) =>
          this.toRow(n.team, n.depth),
        )
      : [],
  );
  /** The teams that the chip shows, before the search. */
  readonly visibleCount = computed(
    () => this.store.teams().filter((t) => t.isMember || this.showsOthers()).length,
  );

  readonly searchPlaceholder = computed(() =>
    searchPlaceholder(
      this.i18n,
      { plain: 'gremien.list.searchLabel', one: 'gremien.list.searchOne', many: 'gremien.list.search' },
      this.visibleCount(),
      this.showSkeleton(),
    ),
  );

  /** "Team anlegen": a team at the top needs `team.create` (spec 003065). */
  readonly canCreate = computed(() => this.auth.can('team.create'));
  readonly createOpen = signal(false);

  /** The ⋮ menu of the phone header: "Team anlegen" and the calendar subscription. */
  readonly phoneMenu = computed<RowMenuSection[]>(() => [
    {
      items: [
        ...(this.canCreate()
          ? [{ id: 'create', label: this.i18n.translate('teams.create'), icon: 'plus' as const }]
          : []),
        { id: 'calendar', label: this.i18n.translate('gremien.list.subscribe'), icon: 'cal' },
      ],
    },
    refreshMenuSection((key) => this.i18n.translate(key)),
  ]);

  constructor() {
    prefetchDetails({
      items: computed(() => [...this.mine(), ...this.others()]),
      key: (r) => r.team.id,
      reads: (r) => (r.item ? [inject(GremienApiService).meetings(r.item.id)] : []),
    });
    this.store.load();
    effect(() => {
      // An old link `/committees/:id` arrives as `?gremium=`: open the inherent team.
      const gremium = this.gremiumParam();
      if (!gremium || this.store.loading()) return;
      const team = untracked(() => this.store.teamOfGremium(gremium));
      void this.router.navigate(team ? ['/teams', team.id] : ['/teams'], {
        queryParams: { gremium: null },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      });
    });
    effect(() => {
      if (this.store.loading() || this.logosStarted) return;
      this.logosStarted = true;
      const urls = untracked(() => this.store.items())
        .map((g) => g.logoUrl)
        .filter((u): u is string => !!u);
      if (!urls.length) {
        this.logosPending.set(false);
        return;
      }
      void this.preload(urls).then(() => this.logosPending.set(false));
    });
  }

  /** "Zur Liste": close the gremium, keep the tab. */
  closeDetail(): void {
    void this.router.navigate(['/teams'], { queryParamsHandling: 'preserve' });
  }

  setScope(value: string): void {
    this.scope.set(value === 'mine' ? 'mine' : 'all');
  }

  /** The ⋮ menu of the phone header: "Kalender abonnieren" opens the bottom sheet. */
  onPhoneMenu(item: RowMenuItem, abo: CalendarSubscribeComponent): void {
    if (isRefreshItem(item)) return reloadLikePull(() => this.store.refresh());
    if (item.id === 'calendar') abo.open();
    if (item.id === 'create') this.createOpen.set(true);
  }

  /** A new team: read the list again and open the team. */
  created(detail: TeamDetail): void {
    this.store.reloadTeams();
    void this.router.navigate(['/teams', detail.team.id]);
  }

  private toRow(team: Team, depth: number): GremiumRow {
    const item = this.store.find(team.gremiumId);
    if (!item) {
      const role = team.canManage ? 'teams.role.manager' : 'teams.role.member';
      const parent = team.parentName ? this.i18n.translate('teams.subTeamOf', { name: team.parentName }) : '';
      const sub = [parent, team.isMember ? this.i18n.translate(role) : ''].filter(Boolean).join(' · ');
      return { team, item: null, depth, sub, next: { kind: 'none' } };
    }
    const locale = this.i18n.uiLocale();
    const count =
      item.memberCount === 1
        ? this.i18n.translate('gremien.list.member1')
        : this.i18n.translate('gremien.list.members', { n: item.memberCount });
    const role = item.isMember ? localized(item.roleName, locale, item.roleKey ?? '') : '';
    const sub = role ? `${role} · ${count}` : count;
    return { team, item, depth, sub, next: this.nextOf(item) };
  }

  /** The next meeting of a row: running now, a planned date, or none. */
  private nextOf(item: GremiumOverview): GremiumRow['next'] {
    if (item.live) return { kind: 'live' };
    if (!item.nextMeeting?.date) return { kind: 'none' };
    return {
      kind: 'date',
      text: weekdayDate(item.nextMeeting.date, this.i18n.formatLocale(), { year: false }),
      title: this.i18n.translate('gremien.list.nextTitle', { title: item.nextMeeting.title }),
    };
  }
}
