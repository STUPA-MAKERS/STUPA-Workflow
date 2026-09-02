import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { ApplicationListItem, ApplicationType, Meeting, Uuid } from '@core/api/models';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';

/** Max number of application rows shown per panel. */
const PREVIEW_ROWS = 5;

/**
 * Role-based home page. It shows three areas instead of count tiles.
 *
 * Submit application: the primary CTA into the apply wizard (`/apply`).
 * Open tasks: applications that wait for processing or review, each with a deep link.
 * These applications sit in a non-final state.
 * My applications: every application the user can read, with status and a deep link.
 *
 * Below these areas, RBAC-gated quick links lead to votes, meetings, budget, and admin.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    LocalizedDatePipe,
    TranslatePipe,
    BadgeComponent,
    PageHeaderComponent,
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiClient);

  /** "My applications": only the applications the user owns. `mine=true` forces the
   *  owner filter, even for a principal with `application.read`. Without it, the card
   *  would show every application to an entitled user. */
  private readonly applications = toSignal(
    this.api.listApplications({ mine: true }).pipe(catchError(() => of(null))),
    { initialValue: undefined },
  );

  /** "Open tasks": real open decisions (GET /applications/tasks). */
  private readonly tasks = toSignal(
    this.api.listTasks().pipe(catchError(() => of([] as ApplicationListItem[]))),
    { initialValue: [] as ApplicationListItem[] },
  );

  private readonly types = toSignal(
    this.api.applicationTypes({ quiet: true }).pipe(catchError(() => of([] as ApplicationType[]))),
    { initialValue: [] as ApplicationType[] },
  );
  private readonly typeName = computed(() => {
    const map = new Map(this.types().map((t) => [t.id, t.name]));
    return (id: Uuid): string => map.get(id) ?? id;
  });

  /** `true` while the applications endpoint has not responded yet. */
  readonly loading = computed(() => this.applications() === undefined);
  /** `true` if the applications endpoint failed. */
  readonly error = computed(() => this.applications() === null);

  private readonly items = computed<ApplicationListItem[]>(() => this.applications()?.items ?? []);
  readonly total = computed(() => this.applications()?.total ?? 0);

  readonly openTasks = computed(() => this.tasks());

  readonly taskRows = computed(() => this.openTasks().slice(0, PREVIEW_ROWS));
  readonly applicationRows = computed(() => this.items().slice(0, PREVIEW_ROWS));

  name(item: ApplicationListItem): string {
    return this.typeName()(item.typeId);
  }

  titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.typeName()(item.typeId);
  }

  created(item: ApplicationListItem): string | null {
    return item.createdAt ?? null;
  }

  /** The template shows the application panels only when this permission holds. */
  readonly canReadApplications = computed(() => this.auth.canAny('application.read'));

  private readonly meetings = toSignal(
    this.api.listMeetings().pipe(catchError(() => of([] as Meeting[]))),
    { initialValue: [] as Meeting[] },
  );
  /** Live meetings first, then planned ones by date. The list keeps at most 4. */
  readonly sessionShortcuts = computed<Meeting[]>(() => {
    const rank = (m: Meeting): number => (m.status === 'live' ? 0 : m.status === 'planned' ? 1 : 2);
    return this.meetings()
      .filter((m) => m.status !== 'closed')
      .slice()
      .sort((a, b) => rank(a) - rank(b) || (a.date ?? '').localeCompare(b.date ?? ''))
      .slice(0, 4);
  });

  sessionStatusKey(status: Meeting['status']): TranslationKey {
    return `meetings.status.${status}` as TranslationKey;
  }

  sessionVariant(status: Meeting['status']): 'success' | 'info' | 'neutral' {
    return status === 'live' ? 'success' : status === 'planned' ? 'info' : 'neutral';
  }

  readonly gremien = computed(() => this.auth.gremien());

  private readonly delegationsApi = inject(DelegationsApiService);
  private readonly delegationsRaw = toSignal(
    this.delegationsApi.list().pipe(catchError(() => of([] as Delegation[]))),
    { initialValue: [] as Delegation[] },
  );
  /** Only delegations for a planned or live meeting. The server marks those revocable. */
  readonly delegations = computed<Delegation[]>(() =>
    this.delegationsRaw()
      .filter((d) => d.revocable)
      .slice(0, PREVIEW_ROWS),
  );

  /** Outgoing means another person represents the user. The server sets the direction. */
  isOutgoing(d: Delegation): boolean {
    return d.direction === 'outgoing';
  }
}
