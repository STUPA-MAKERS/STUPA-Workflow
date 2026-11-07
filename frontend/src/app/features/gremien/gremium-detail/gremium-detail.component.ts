import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';
import type { GremiumOverview } from '@core/api/gremien.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  EmptyStateComponent,
  IconComponent,
  MEDIA,
  mediaQuery,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SheetBarComponent,
  SheetBarTitleDirective,
  SkeletonComponent,
  type TabItem,
  TabPageDirective,
  TabPagerComponent,
  TabsComponent,
} from '@stupa-makers/ui-kit';
import { PageFrameService } from '../../../layout/page-frame.service';
import { CalendarSubscribeComponent } from '../../meetings/calendar-subscribe/calendar-subscribe.component';
import { CreateMeetingDialogComponent } from '../../meetings/create-meeting-dialog/create-meeting-dialog.component';
import { GremienComponent } from '../gremien-page/gremien.component';
import { GremienStore } from '../gremien.store';
import { localized } from '../gremien.util';
import { GremiumAttendanceComponent } from '../gremium-attendance/gremium-attendance.component';
import { GremiumDecisionsComponent } from '../gremium-decisions/gremium-decisions.component';
import { GremiumLogoComponent } from '../gremium-logo/gremium-logo.component';
import { GremiumMeetingsComponent } from '../gremium-meetings/gremium-meetings.component';
import { GremiumMembersComponent } from '../gremium-members/gremium-members.component';

/** The sub-tabs of a gremium, as they stand in `?tab=`. */
export const GREMIUM_TABS = ['sitzungen', 'mitglieder', 'anwesenheit', 'beschluesse'] as const;
export type GremiumTab = (typeof GREMIUM_TABS)[number];

/**
 * One gremium (`/gremien/:id`): the detail sheet beside the list.
 *
 * The header holds the kicker "Gremium · Deine Rolle: X", the calendar subscription, "In
 * der Verwaltung öffnen" (only with `admin.gremien`) and the ⋮ menu; then the logo, the
 * name and the facts that are true ("N Mitglieder · Quorum X % · Protokolle öffentlich ·
 * Vertretung erlaubt"). "Sitzung planen" (only with `session.manage` in the gremium) opens
 * the create dialog of the meetings with the gremium chosen; "Nächste Sitzung öffnen"
 * opens the live or the next meeting.
 *
 * Four sub-tabs follow, kept in `?tab=` so a link opens one of them: Sitzungen,
 * Mitglieder, Anwesenheit, Beschlüsse. A tab loads its data when it opens first and keeps
 * it while the gremium stays open.
 *
 * On a phone the header holds the title and one action; the rest moves into the ⋮ menu.
 */
@Component({
  selector: 'app-gremium-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.gd-host--split]': 'split()' },
  imports: [
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    TabPageDirective,
    TabPagerComponent,
    TabsComponent,
    EmptyStateComponent,
    RowMenuComponent,
    SheetBarComponent,
    SheetBarTitleDirective,
    SkeletonComponent,
    CalendarSubscribeComponent,
    CreateMeetingDialogComponent,
    GremiumLogoComponent,
    GremiumMeetingsComponent,
    GremiumMembersComponent,
    GremiumAttendanceComponent,
    GremiumDecisionsComponent,
  ],
  templateUrl: './gremium-detail.component.html',
  styleUrl: './gremium-detail.component.scss',
})
export class GremiumDetailComponent {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly page = inject(GremienComponent, { optional: true });
  protected readonly store = inject(GremienStore);

  readonly phone = mediaQuery(MEDIA.phone);
  /** The list sits beside the sheet: the sheet fills the pane and scrolls inside. */
  readonly split = computed(() => this.page?.split() ?? false);

  readonly id = toSignal(this.route.paramMap.pipe(map((p) => p.get('id'))), {
    initialValue: this.route.snapshot.paramMap.get('id'),
  });
  private readonly tabParam = toSignal(this.route.queryParamMap.pipe(map((q) => q.get('tab'))), {
    initialValue: this.route.snapshot.queryParamMap.get('tab'),
  });

  readonly gremium = computed<GremiumOverview | null>(() => this.store.find(this.id()));
  readonly tab = computed<GremiumTab>(() => {
    const t = this.tabParam();
    return (GREMIUM_TABS as readonly string[]).includes(t ?? '') ? (t as GremiumTab) : 'sitzungen';
  });
  /** The tabs that were open once for this gremium: their panels stay rendered. */
  readonly visited = signal<ReadonlySet<string>>(new Set());
  /** The number of meetings, once the tab "Sitzungen" loaded them. */
  readonly meetingCount = signal<number | null>(null);

  readonly createOpen = signal(false);
  /** The gremium whose tabs `visited` holds: a new one starts the set again. */
  private shownId: string | null = null;

  readonly roleLabel = computed(() => {
    const g = this.gremium();
    return g?.isMember ? localized(g.roleName, this.i18n.uiLocale(), g.roleKey ?? '') : '';
  });

  /** The facts that are true, in display order. */
  readonly facts = computed<string[]>(() => {
    const g = this.gremium();
    if (!g) return [];
    const role = this.roleLabel();
    const i18n = this.i18n;
    return [
      ...(role ? [`${i18n.translate('gremien.detail.yourRole')} ${role}`] : []),
      g.memberCount === 1
        ? i18n.translate('gremien.list.member1')
        : i18n.translate('gremien.list.members', { n: g.memberCount }),
      ...(g.quorumPercent !== null
        ? [i18n.translate('gremien.detail.quorum', { n: g.quorumPercent })]
        : []),
      ...(g.protocolsPublic ? [i18n.translate('gremien.detail.protocolsPublic')] : []),
      ...(g.allowVoteDelegation ? [i18n.translate('gremien.detail.delegation')] : []),
    ];
  });

  /** "Sitzung planen": `session.manage` in this gremium (the admin passes). */
  readonly canPlan = computed(() => {
    const id = this.id();
    return !!id && this.auth.canInGremium(id, 'session.manage');
  });
  readonly canAdmin = computed(() => this.auth.can('admin.gremien'));
  /** The phone shows one main action: "Sitzung planen", else "Nächste Sitzung öffnen". */
  readonly showNext = computed(
    () => !!this.gremium()?.nextMeeting && (!this.phone() || !this.canPlan()),
  );

  readonly tabs = computed<TabItem[]>(() => {
    const g = this.gremium();
    return [
      { id: 'sitzungen', label: this.i18n.translate('gremien.tab.meetings'), count: this.meetingCount() },
      { id: 'mitglieder', label: this.i18n.translate('gremien.tab.members'), count: g?.memberCount ?? null },
      { id: 'anwesenheit', label: this.i18n.translate('gremien.tab.attendance') },
      { id: 'beschluesse', label: this.i18n.translate('gremien.tab.decisions') },
    ];
  });

  readonly menu = computed<RowMenuSection[]>(() => {
    const g = this.gremium();
    const t = (k: Parameters<I18nService['translate']>[0]) => this.i18n.translate(k);
    const phoneItems = this.phone() ? this.phoneMenu(g, t) : [];
    const items: RowMenuItem[] = [
      ...phoneItems,
      { id: 'meetings', label: t('gremien.detail.allMeetings'), icon: 'users' },
      { id: 'votes', label: t('gremien.detail.votes'), icon: 'vote' },
    ];
    return [{ items }];
  });

  /** The menu items only the phone shows: calendar, the next meeting and the admin page. */
  private phoneMenu(
    g: GremiumOverview | null,
    t: (k: TranslationKey) => string,
  ): readonly RowMenuItem[] {
    const next: readonly RowMenuItem[] =
      g?.nextMeeting && !this.showNext()
        ? [
            {
              id: 'next',
              label: t(g.live ? 'gremien.detail.live' : 'gremien.detail.next'),
              icon: 'arrow',
            },
          ]
        : [];
    const admin: readonly RowMenuItem[] = this.canAdmin()
      ? [{ id: 'admin', label: t('gremien.detail.admin'), icon: 'shield' }]
      : [];
    const calendar: RowMenuItem = {
      id: 'calendar',
      label: t('gremien.detail.subscribe'),
      icon: 'cal',
    };
    return [calendar, ...next, ...admin];
  }

  /**
   * On a phone the tabs beside the active one render too, because a swipe shows them before they
   * are active.
   */
  constructor() {
    effect(() => {
      const id = this.id();
      const tab = this.tab();
      const i = GREMIUM_TABS.indexOf(tab);
      const open = this.phone() ? GREMIUM_TABS.filter((_, j) => Math.abs(j - i) <= 1) : [tab];
      if (id !== this.shownId) {
        this.shownId = id;
        this.meetingCount.set(null);
        this.visited.set(new Set(open));
        return;
      }
      const seen = untracked(this.visited);
      if (open.some((t) => !seen.has(t))) this.visited.set(new Set([...seen, ...open]));
    });

    const frame = inject(PageFrameService);
    effect(() => {
      const g = this.gremium();
      frame.crumbLabel.set(g ? { url: `/gremien/${g.id}`, label: g.name } : null);
    });
    inject(DestroyRef).onDestroy(() => frame.crumbLabel.set(null));
  }

  selectTab(id: string | null): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { tab: id === 'sitzungen' ? null : id },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  /** "Nächste Sitzung öffnen": the live meeting, else the next planned one. */
  openNext(): void {
    const next = this.gremium()?.nextMeeting;
    if (next) void this.router.navigate(['/meetings', next.id]);
  }

  openAdmin(): void {
    const id = this.id();
    if (id) void this.router.navigate(['/admin/gremien', id, 'members']);
  }

  onMenu(item: RowMenuItem, abo: CalendarSubscribeComponent): void {
    switch (item.id) {
      case 'calendar':
        abo.open();
        break;
      case 'next':
        this.openNext();
        break;
      case 'admin':
        this.openAdmin();
        break;
      case 'meetings':
        void this.router.navigate(['/meetings']);
        break;
      case 'votes':
        void this.router.navigate(['/voting'], { queryParams: { gremium: this.id() } });
        break;
    }
  }
}
