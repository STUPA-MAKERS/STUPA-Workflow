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
import { NgTemplateOutlet } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import type { GremiumOverview } from '@core/api/gremien.service';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import {
  ButtonComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
  ListDetailLayoutComponent,
  ListItemComponent,
  MEDIA,
  mediaQuery,
  NoteComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  SearchPillComponent,
  SkeletonComponent,
  StickyBarComponent,
} from '@stupa-makers/ui-kit';
import { PageFrameService } from '../../../layout/page-frame.service';
import { CalendarSubscribeComponent } from '../../meetings/calendar-subscribe/calendar-subscribe.component';
import { GremienApiService } from '@core/api/gremien.service';
import { prefetchDetails } from '@core/cache/detail-prefetch';
import { GremienStore } from '../gremien.store';
import { localized } from '../gremien.util';
import { weekdayDate } from '@shared/date-format';
import { GremiumLogoComponent } from '../gremium-logo/gremium-logo.component';
import { RowChevronComponent } from '@shared/ui/row-chevron/row-chevron.component';
import { PullRefreshDirective } from '@shared/ui/pull-refresh/pull-refresh.directive';

/** The permission that shows every gremium, also without a membership. */
export const GREMIUM_VIEW_ALL = 'gremium.view_all';

/** The chip "Anzeigen": the own gremien, or every visible gremium. */
export type GremienScope = 'mine' | 'all';

/** One row of the list, ready for the template. */
export interface GremiumRow {
  readonly item: GremiumOverview;
  readonly sub: string;
  /** `live`, a date ("Di, 20.10."), or `none`. */
  readonly next: { kind: 'live' } | { kind: 'date'; text: string; title: string } | { kind: 'none' };
}

/**
 * The tab "Gremien" (`/gremien`): a list/detail pane page like the votes.
 *
 * - Left: the title with the calendar subscription, the search and, with
 *   `gremium.view_all`, the chip "Anzeigen: Meine Gremien | Alle Gremien". Then the groups
 *   "Meine Gremien" (with the own role) and "Weitere Gremien". A row shows the square logo
 *   or the initials, the role and the number of members, and the next meeting ("Läuft",
 *   a date or "keine geplant").
 * - Right: the child route `/gremien/:id` with the open gremium (`GremiumDetailComponent`).
 *   Side by side the first own gremium opens by itself.
 * - One pane at a time (narrow, phone): the list, then the gremium with a way back.
 *
 * The search filters the loaded list in the browser: the list is short and complete.
 */
@Component({
  selector: 'app-gremien',
  // A pane page (styles.scss): side by side the panes fill the free height.
  host: { '[class.pane-page]': 'split()' },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PullRefreshDirective,
    RowChevronComponent,
    NoteComponent,
    NgTemplateOutlet,
    RouterOutlet,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    ListDetailLayoutComponent,
    ListItemComponent,
    PageHeaderComponent,
    RowMenuComponent,
    SearchPillComponent,
    SkeletonComponent,
    StickyBarComponent,
    ScrollFadeDirective,
    CalendarSubscribeComponent,
    GremiumLogoComponent,
  ],
  providers: [GremienStore],
  templateUrl: './gremien.component.html',
  styleUrl: './gremien.component.scss',
})
export class GremienComponent implements OnDestroy {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly frame = inject(PageFrameService);
  protected readonly store = inject(GremienStore);

  readonly phone = mediaQuery(MEDIA.phone);

  private readonly layout = viewChild(ListDetailLayoutComponent);
  /** The list and the detail sit side by side. */
  readonly split = computed(() => this.layout()?.collapsed() === false);

  /** The gremium of the child route `:id`. */
  readonly selectedId = signal<Uuid | null>(null);

  readonly query = signal('');
  /** The chip "Anzeigen" shows only with `gremium.view_all`. */
  readonly viewAll = computed(() => this.auth.can(GREMIUM_VIEW_ALL));
  readonly scope = signal<GremienScope>('all');

  readonly scopeOptions = computed<FilterSelectOption[]>(() => [
    { value: 'mine', label: this.i18n.translate('gremien.list.showMine') },
    { value: 'all', label: this.i18n.translate('gremien.list.showAll') },
  ]);
  readonly scopeText = computed(() => {
    const label = this.scopeOptions().find((o) => o.value === this.scope())?.label ?? '';
    return `${this.i18n.translate('gremien.list.show')}: ${label}`;
  });

  /** The rows that match the search, in the order of the server (by name). */
  private readonly matching = computed(() => {
    const q = this.query().trim().toLocaleLowerCase(this.i18n.locale());
    const items = this.store.items();
    if (!q) return items;
    return items.filter(
      (g) =>
        g.name.toLocaleLowerCase(this.i18n.locale()).includes(q) ||
        g.slug.toLocaleLowerCase().includes(q),
    );
  });

  readonly mine = computed(() =>
    this.matching()
      .filter((g) => g.isMember)
      .map((g) => this.toRow(g)),
  );
  readonly others = computed(() =>
    this.viewAll() && this.scope() === 'all'
      ? this.matching()
          .filter((g) => !g.isMember)
          .map((g) => this.toRow(g))
      : [],
  );
  /** The gremien that the chip shows, before the search. */
  readonly visibleCount = computed(
    () =>
      this.store.items().filter((g) => g.isMember || (this.viewAll() && this.scope() === 'all'))
        .length,
  );

  readonly searchPlaceholder = computed(() =>
    this.i18n.translate('gremien.list.search', { n: this.visibleCount() }),
  );

  /** The ⋮ menu of the phone header: the calendar subscription. */
  readonly phoneMenu = computed<RowMenuSection[]>(() => [
    {
      items: [{ id: 'calendar', label: this.i18n.translate('gremien.list.subscribe'), icon: 'cal' }],
    },
  ]);

  constructor() {
    // The shown gremien read their first tab ahead, so a click shows it at once.
    prefetchDetails({
      items: computed(() => [...this.mine(), ...this.others()]),
      key: (r) => r.item.id,
      reads: (r) => [inject(GremienApiService).meetings(r.item.id)],
    });
    this.store.load();
    this.readSelection();
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.readSelection());

    effect(() => this.frame.fill.set(this.split()));

    // Side by side a gremium always shows: the first own one, else the first visible one.
    effect(() => {
      const split = this.split();
      const loading = this.store.loading();
      const first = this.mine()[0] ?? this.others()[0];
      untracked(() => {
        if (!split || loading || this.selectedId() || !first) return;
        void this.router.navigate(['/gremien', first.item.id], {
          queryParamsHandling: 'preserve',
          replaceUrl: true,
        });
      });
    });
  }

  ngOnDestroy(): void {
    this.frame.fill.set(false);
  }

  /** "Zur Liste": close the gremium, keep the tab. */
  closeDetail(): void {
    void this.router.navigate(['/gremien'], { queryParamsHandling: 'preserve' });
  }

  setScope(value: string): void {
    this.scope.set(value === 'mine' ? 'mine' : 'all');
  }

  /** The ⋮ menu of the phone header: "Kalender abonnieren" opens the bottom sheet. */
  onPhoneMenu(item: RowMenuItem, abo: CalendarSubscribeComponent): void {
    if (item.id === 'calendar') abo.open();
  }

  private readSelection(): void {
    this.selectedId.set(this.route.snapshot.firstChild?.paramMap.get('id') ?? null);
  }

  private toRow(item: GremiumOverview): GremiumRow {
    const locale = this.i18n.locale();
    const count =
      item.memberCount === 1
        ? this.i18n.translate('gremien.list.member1')
        : this.i18n.translate('gremien.list.members', { n: item.memberCount });
    const role = item.isMember ? localized(item.roleName, locale, item.roleKey ?? '') : '';
    const sub = role ? `${role} · ${count}` : count;
    let next: GremiumRow['next'] = { kind: 'none' };
    if (item.live) next = { kind: 'live' };
    else if (item.nextMeeting?.date) {
      next = {
        kind: 'date',
        text: weekdayDate(item.nextMeeting.date, this.i18n.formatLocale(), { year: false }),
        title: this.i18n.translate('gremien.list.nextTitle', { title: item.nextMeeting.title }),
      };
    }
    return { item, sub, next };
  }
}
