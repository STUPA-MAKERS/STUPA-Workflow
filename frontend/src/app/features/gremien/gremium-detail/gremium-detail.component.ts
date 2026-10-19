import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';
import type { GremiumOverview } from '@core/api/gremien.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
} from '@shared/ui/row-menu/row-menu.component';
import { SheetBarComponent, SheetBarTitleDirective } from '@shared/ui/sheet-bar/sheet-bar.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { ButtonComponent, IconComponent, MEDIA, TabsComponent, type TabItem } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
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
    TranslatePipe,
    ButtonComponent,
    IconComponent,
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

  readonly phone = mediaQuerySignal(MEDIA.phone);
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
  readonly visited = signal<ReadonlySet<GremiumTab>>(new Set());
  /** The number of meetings, once the tab "Sitzungen" loaded them. */
  readonly meetingCount = signal<number | null>(null);

  readonly createOpen = signal(false);

  readonly roleLabel = computed(() => {
    const g = this.gremium();
    return g?.isMember ? localized(g.roleName, this.i18n.locale(), g.roleKey ?? '') : '';
  });

  /** The facts that are true, in the order of the board. */
  readonly facts = computed<string[]>(() => {
    const g = this.gremium();
    if (!g) return [];
    const role = this.roleLabel();
    const out = role ? [`${this.i18n.translate('gremien.detail.yourRole')} ${role}`] : [];
    out.push(
      g.memberCount === 1
        ? this.i18n.translate('gremien.list.member1')
        : this.i18n.translate('gremien.list.members', { n: g.memberCount }),
    );
    if (g.quorumPercent !== null) {
      out.push(this.i18n.translate('gremien.detail.quorum', { n: g.quorumPercent }));
    }
    if (g.protocolsPublic) out.push(this.i18n.translate('gremien.detail.protocolsPublic'));
    if (g.allowVoteDelegation) out.push(this.i18n.translate('gremien.detail.delegation'));
    return out;
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
    const items: RowMenuItem[] = [];
    if (this.phone()) {
      items.push({ id: 'calendar', label: t('gremien.detail.subscribe'), icon: 'cal' });
      if (g?.nextMeeting && !this.showNext()) {
        items.push({ id: 'next', label: t(g.live ? 'gremien.detail.live' : 'gremien.detail.next'), icon: 'arrow' });
      }
      if (this.canAdmin()) items.push({ id: 'admin', label: t('gremien.detail.admin'), icon: 'shield' });
    }
    items.push({ id: 'meetings', label: t('gremien.detail.allMeetings'), icon: 'users' });
    items.push({ id: 'votes', label: t('gremien.detail.votes'), icon: 'vote' });
    return [{ items }];
  });

  constructor() {
    // The tab of the URL opens and stays rendered; a new gremium starts afresh.
    let shownId: string | null = null;
    effect(() => {
      const id = this.id();
      const tab = this.tab();
      if (id !== shownId) {
        shownId = id;
        this.meetingCount.set(null);
        this.visited.set(new Set([tab]));
        return;
      }
      if (!this.visited().has(tab)) this.visited.set(new Set([...this.visited(), tab]));
    });

    // The breadcrumb names the gremium, not the page.
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
