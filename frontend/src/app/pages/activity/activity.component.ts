import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import type { Subscription } from 'rxjs';
import {
  ACTIVITY_KINDS,
  ActivityApiService,
  type ActivityEntry,
  type ActivityItemKind,
  type ActivityPage,
} from '@core/api/activity.service';
import { FeatureService } from '@core/features/feature.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { clock, isoDay, localToday, weekdayDate } from '@shared/date-format';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import { RowChevronComponent } from '@shared/ui/row-chevron/row-chevron.component';
import { RouterLink } from '@angular/router';
import { FabLinkDirective } from '@stupa-makers/ui-kit/shell';
import { LiveCardsComponent } from '../../features/meetings/live-cards/live-cards.component';
import { injectPanePage } from '../admin/pane-page';
import { RailStatusService } from '../../layout/rail-status.service';
import {
  ButtonComponent,
  ButtonGroupComponent,
  ButtonLinkComponent,
  EmptyStateComponent,
  FabComponent,
  FilterSelectComponent,
  IconComponent,
  type IconName,
  InfiniteScrollDirective,
  ListGroupComponent,
  ListItemComponent,
  MEDIA,
  PageHeaderComponent,
  ScrollFadeDirective,
  SkeletonComponent,
  StickyBarComponent,
  mediaQuery,
} from '@stupa-makers/ui-kit';

/** The icon of each kind of item, the same as its navigation entry. */
export const KIND_ICON: Readonly<Record<ActivityItemKind, IconName>> = {
  application: 'file',
  todo: 'circleok',
  ticket: 'ticket',
  meeting: 'users',
};

/** The feature a kind of item needs; an Antrag needs none. */
const KIND_FEATURE: Partial<Record<ActivityItemKind, 'todos' | 'tickets' | 'meetings'>> = {
  todo: 'todos',
  ticket: 'tickets',
  meeting: 'meetings',
};

/** One day of the page: its label and its rows. */
export interface ActivityDay {
  readonly key: string;
  readonly label: string;
  readonly entries: readonly ActivityEntry[];
}

/**
 * The page "Aktivität" (`/activity`, specs 001270-001277): the events of the Anträge,
 * To-Dos, Tickets and Sitzungen that the person made, holds or touched, newest first and
 * grouped by day.
 *
 * The filter "Art" limits the kinds (none selected shows all), the filter "Von" shows the
 * own actions too (hidden by default, the choice stays in this browser). A row opens the
 * item. A row after the last visit carries a dot; the first step that loads sets the
 * visit mark to the `readAt` of the server, and the dot of the navigation goes at once.
 * The page loads 50 rows per step and the next 50 at the end of the list.
 *
 * It is the start page of a signed-in person (spec 001300): above the list it shows the
 * live meetings (spec 001302), and "Antrag stellen" is the one action of the header, on a
 * phone the floating button (spec 001301).
 */
@Component({
  selector: 'app-activity',
  standalone: true,
  host: { '[class.pane-page]': '!phone()' },
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    ButtonLinkComponent,
    EmptyStateComponent,
    FabComponent,
    FabLinkDirective,
    FilterSelectComponent,
    LiveCardsComponent,
    RouterLink,
    IconComponent,
    InfiniteScrollDirective,
    ListGroupComponent,
    ListItemComponent,
    LoadErrorComponent,
    PageHeaderComponent,
    RowChevronComponent,
    ScrollFadeDirective,
    SkeletonComponent,
    StickyBarComponent,
  ],
  templateUrl: './activity.component.html',
  styleUrl: './activity.component.scss',
})
export class ActivityComponent {
  private readonly api = inject(ActivityApiService);
  private readonly i18n = inject(I18nService);
  private readonly features = inject(FeatureService);
  private readonly rail = inject(RailStatusService);
  private readonly destroyRef = inject(DestroyRef);

  /** The key of the stored choice of "Von" (spec 001273). */
  static readonly OWN_KEY = 'ap.activity.own';

  readonly phone = mediaQuery(MEDIA.phone);

  readonly kinds = signal<readonly string[]>([]);
  readonly own = signal(readOwn());

  readonly entries = signal<readonly ActivityEntry[]>([]);
  readonly cursor = signal<string | null>(null);
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly error = signal(false);

  private request: Subscription | null = null;
  private marked = false;

  readonly kindOptions = computed(() =>
    ACTIVITY_KINDS.filter((k) => {
      const feature = KIND_FEATURE[k];
      return !feature || this.features.isOn(feature);
    }).map((k) => ({ value: k, label: this.i18n.translate(`activity.kind.${k}`) })),
  );

  readonly whoOptions = computed(() => [
    { value: '', label: this.i18n.translate('activity.filter.others') },
    { value: 'own', label: this.i18n.translate('activity.filter.own') },
  ]);

  readonly filtered = computed(() => this.kinds().length > 0 || this.own());

  readonly days = computed<readonly ActivityDay[]>(() =>
    groupByDay(this.entries(), this.i18n.locale(), (key) => this.i18n.translate(key)),
  );

  constructor() {
    // Beside the rail the page fills the window and only the list scrolls, so the head and the
    // filters keep their place (`pane-page`): without it the window scrolls by the bottom
    // padding of the page as well.
    injectPanePage(computed(() => !this.phone()));
    effect(() => {
      const kinds = this.kinds();
      const own = this.own();
      untracked(() => this.load(kinds, own));
    });
    this.destroyRef.onDestroy(() => this.request?.unsubscribe());
  }

  setKinds(values: readonly string[]): void {
    this.kinds.set(values);
  }

  setWho(value: string): void {
    const own = value === 'own';
    this.own.set(own);
    writeOwn(own);
  }

  retry(): void {
    this.load(this.kinds(), this.own());
  }

  loadMore(): void {
    const cursor = this.cursor();
    if (!cursor || this.loadingMore() || this.loading()) return;
    this.loadingMore.set(true);
    this.request = this.fetch(cursor).subscribe({
      next: (page) => {
        this.entries.update((rows) => [...rows, ...page.entries]);
        this.cursor.set(page.nextCursor);
        this.loadingMore.set(false);
      },
      error: () => this.loadingMore.set(false),
    });
  }

  icon(e: ActivityEntry): IconName {
    return KIND_ICON[e.itemKind];
  }

  title(e: ActivityEntry): string {
    return e.itemTitle || this.i18n.translate('activity.untitled');
  }

  /** "Bob · Kommentar: Danke" — the actor and the change, as the row's second line. */
  sub(e: ActivityEntry): string {
    return `${this.actor(e)} · ${this.change(e)}`;
  }

  actor(e: ActivityEntry): string {
    if (e.own) return this.i18n.translate('activity.actor.you');
    switch (e.actor.kind) {
      case 'system':
        return this.i18n.translate('activity.actor.system');
      case 'applicant':
        return this.i18n.translate('activity.actor.applicant');
      case 'committee':
        return this.i18n.translate('activity.actor.committee');
      default:
        return e.actor.name || this.i18n.translate('common.unnamed');
    }
  }

  change(e: ActivityEntry): string {
    return this.i18n.translate(`activity.change.${e.change}` as TranslationKey, { detail: this.detail(e) });
  }

  time(e: ActivityEntry): string {
    return clock(e.at, this.i18n.locale());
  }

  private detail(e: ActivityEntry): string {
    if (e.status) {
      const key = e.itemKind === 'ticket' ? `tickets.status.${e.status}` : `meetings.status.${e.status}`;
      return this.i18n.translate(key as TranslationKey);
    }
    return e.detail ?? '';
  }

  private load(kinds: readonly string[], own: boolean): void {
    this.request?.unsubscribe();
    this.loading.set(true);
    this.error.set(false);
    this.request = this.fetch(null, kinds as readonly ActivityItemKind[], own).subscribe({
      next: (page) => {
        this.entries.set(page.entries);
        this.cursor.set(page.nextCursor);
        this.loading.set(false);
        this.markSeen(page);
      },
      error: () => {
        this.entries.set([]);
        this.cursor.set(null);
        this.loading.set(false);
        this.error.set(true);
      },
    });
  }

  private fetch(
    cursor: string | null,
    kinds: readonly ActivityItemKind[] = this.kinds() as readonly ActivityItemKind[],
    own: boolean = this.own(),
  ) {
    return this.api.list({ kinds, own, cursor, lang: this.i18n.uiLocale() });
  }

  /** The first step of an unfiltered visit sets the mark (spec 001275). */
  private markSeen(page: ActivityPage): void {
    if (this.marked) return;
    this.marked = true;
    this.rail.activitySeen();
    this.api.markSeen(page.readAt).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({ error: () => undefined });
  }
}

/**
 * The rows by local day, newest first: "Heute", "Gestern", then the short weekday and date ("Mo, 16.11.2026").
 */
export function groupByDay(
  entries: readonly ActivityEntry[],
  locale: string,
  t: (key: TranslationKey) => string,
  now: Date = new Date(),
): readonly ActivityDay[] {
  const today = localToday(now);
  const yesterday = localToday(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
  const label = (key: string): string =>
    key === today ? t('activity.today') : key === yesterday ? t('activity.yesterday') : weekdayDate(key, locale);
  return entries.reduce<readonly ActivityDay[]>((days, e) => {
    const key = isoDay(new Date(e.at));
    const last = days.at(-1);
    return last?.key === key
      ? [...days.slice(0, -1), { ...last, entries: [...last.entries, e] }]
      : [...days, { key, label: label(key), entries: [e] }];
  }, []);
}

function readOwn(): boolean {
  try {
    return localStorage.getItem(ActivityComponent.OWN_KEY) === '1';
  } catch {
    return false;
  }
}

function writeOwn(own: boolean): void {
  try {
    if (own) localStorage.setItem(ActivityComponent.OWN_KEY, '1');
    else localStorage.removeItem(ActivityComponent.OWN_KEY);
  } catch {
    // Storage blocked: the choice lasts for this visit only.
  }
}
