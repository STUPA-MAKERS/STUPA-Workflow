import {
  ChangeDetectionStrategy,
  Component,
  computed,
  forwardRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, Router, RouterOutlet } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicantApplications, Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { LOCATION } from '@core/browser/location.token';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { formatMoney } from '@shared/format-money';
import { resolveI18n } from '@shared/forms/i18n-text';
import { groupByMonth, type MonthGroup } from '@shared/group-by-month';
import { flowColorKind } from '@shared/status-kind.util';
import { AmountComponent } from '@shared/ui/amount/amount.component';
import {
  EmptyStateComponent,
  IconComponent,
  ListDetailLayoutComponent,
  ListGroupComponent,
  ListItemComponent,
  PageHeaderComponent,
  ScrollFadeDirective,
  SearchPillComponent,
  StickyBarComponent,
  SkeletonComponent,
  StatusTextComponent,
  type StatusKind,
} from '@stupa-makers/ui-kit';
import { injectListDetailPage } from '@stupa-makers/ui-kit/shell';
import { MY_APPLICATIONS_PAGE, type MyApplicationsPage } from './my-applications-page';

/** One row of the list, in the shape of the rows of the list "Anträge". */
interface MyRow {
  readonly id: Uuid;
  readonly createdAt: string;
  readonly title: string;
  readonly stateLabel: string;
  readonly stateKind: StatusKind;
  readonly typeLabel: string;
  readonly amount: string | null;
  readonly approved: string | null;
  /** The address only observes this Antrag (spec 000752). */
  readonly observed: boolean;
}

/**
 * The page `/my-applications`: the Anträge of an applicant session as a list with a detail
 * pane, like the list "Anträge" of a member. `/my-applications/<id>` opens one Antrag.
 *
 * The login link of the mail opens this page with the token in the fragment (`#t=`). The
 * page posts the token, strips it from the URL and loads the list. Without a token it
 * reuses the cookie session. An invalid link or a missing session leads to `/login`; an
 * invalid link adds `?link=invalid`, so the login page says why. An old link of one Antrag
 * arrives as `/my-applications/<id>#t=`; the detail pane redeems it.
 */
@Component({
  selector: 'app-my-applications',
  host: { '[class.pane-page]': 'split()' },
  providers: [{ provide: MY_APPLICATIONS_PAGE, useExisting: forwardRef(() => MyApplicationsComponent) }],
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    TranslatePipe,
    AmountComponent,
    EmptyStateComponent,
    IconComponent,
    ListDetailLayoutComponent,
    ListGroupComponent,
    ListItemComponent,
    PageHeaderComponent,
    ScrollFadeDirective,
    SearchPillComponent,
    StickyBarComponent,
    SkeletonComponent,
    StatusTextComponent,
  ],
  templateUrl: './my-applications.component.html',
  styleUrl: './my-applications.component.scss',
})
export class MyApplicationsComponent implements MyApplicationsPage {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly location = inject(LOCATION);
  private readonly i18n = inject(I18nService);

  private readonly layout = viewChild(ListDetailLayoutComponent);
  private readonly listDetail = injectListDetailPage(this.layout);
  /** The list and the detail sit side by side. */
  readonly split = this.listDetail.split;
  readonly selectedId = this.listDetail.selectedId;

  readonly loading = signal(true);
  readonly data = signal<ApplicantApplications | null>(null);

  /** The search text; the list filters the loaded rows by title. */
  readonly query = signal('');
  /** The names of the application types, for "Status · Typ". */
  private readonly typeNames = signal<ReadonlyMap<string, string>>(new Map());

  /** The rows, built like the rows of the list "Anträge". */
  readonly rows = computed<readonly MyRow[]>(() => {
    const lang = this.i18n.locale();
    const untitled = this.i18n.translate('applications.list.untitled');
    const needle = this.query().trim().toLocaleLowerCase();
    return (this.data()?.items ?? [])
      .map((item) => ({
        id: item.id,
        createdAt: item.createdAt,
        title: item.title?.trim() || untitled,
        stateLabel: item.state ? resolveI18n(item.state.label, lang) : '',
        stateKind: flowColorKind(item.state?.color),
        typeLabel: this.typeNames().get(item.typeId) ?? '',
        amount: this.money(item.amount, item.currency),
        approved:
          item.approvedAmount !== null && item.amount !== null && Number(item.approvedAmount) !== Number(item.amount)
            ? this.money(item.approvedAmount, item.currency)
            : null,
        observed: item.observed ?? false,
      }))
      .filter((row) => !needle || row.title.toLocaleLowerCase().includes(needle));
  });

  /** The rows by month of submission, as in the list "Anträge". */
  readonly groups = computed<MonthGroup<MyRow>[]>(() =>
    groupByMonth(this.rows(), (r) => r.createdAt, this.i18n.formatLocale()),
  );

  /** "3 Anträge durchsuchen", as in the list "Anträge". */
  readonly searchPlaceholder = computed(() => {
    const total = this.data()?.items.length ?? 0;
    if (this.loading()) return this.i18n.translate('applications.list.searchPlain');
    if (total === 1) return this.i18n.translate('applications.list.searchCountOne');
    return this.i18n.translate('applications.list.searchCount', { count: total });
  });

  constructor() {
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (types) => this.typeNames.set(new Map(types.map((t) => [t.id, t.name]))),
      error: () => this.typeNames.set(new Map()),
    });
    const childId = this.route.snapshot.firstChild?.paramMap.get('id') ?? null;
    const token = new URLSearchParams(this.route.snapshot.fragment ?? '').get('t');
    if (token && !childId) {
      this.api.verifyEmailLogin(token).subscribe({
        next: () => {
          this.stripToken();
          this.load();
        },
        error: () => {
          this.stripToken();
          void this.router.navigate(['/login'], { queryParams: { link: 'invalid' }, replaceUrl: true });
        },
      });
    } else if (!token) {
      this.load();
    }
  }

  /** Reload the list, for example after the detail pane redeemed an old link. */
  reload(): void {
    this.load();
  }

  /** Load the list; no session leads to `/login`. */
  load(): void {
    this.api.applicantApplications().subscribe({
      next: (res) => {
        this.auth.markApplicantSession();
        this.data.set(res);
        this.loading.set(false);
      },
      error: () => void this.router.navigate(['/login'], { replaceUrl: true }),
    });
  }

  /** The amount in its currency, or null without an amount. */
  private money(amount: string | null, currency: string | null): string | null {
    if (amount === null) return null;
    return formatMoney(amount, this.i18n.formatLocale(), { currency: currency ?? undefined }) || amount;
  }

  /** "Zur Liste" (narrow layout): close the detail. */
  onBack(): void {
    void this.router.navigate(['/my-applications']);
  }

  /** The token must not stay in the history or reach a Referer. */
  private stripToken(): void {
    if (typeof history === 'undefined') return;
    const { pathname, search } = this.location;
    history.replaceState(history.state, '', `${pathname}${search}`);
  }
}
