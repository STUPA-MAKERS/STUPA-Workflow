import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import type { Uuid } from '@core/api/models';
import { errorStatus } from '@core/api/problem';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  AvatarComponent,
  ButtonComponent,
  ButtonGroupComponent,
  ConfirmDialogComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  filterChipText,
  type ListRow,
  type LoadState,
  NoteComponent,
  SearchPillComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  RecordsScreenComponent,
  ScreenFiltersDirective,
  ScreenListFootDirective,
  ScreenRecordDirective,
  ScreenSearchDirective,
} from '@stupa-makers/ui-kit/screens';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, OAuthGrantAdmin } from '../admin.models';
import { personLabel } from '@shared/person-label.util';
import { debounced } from '@shared/debounced';

/**
 * The most scope tags per row. A token usually carries every scope, and all of them would
 * wrap each row over three lines and set the height of the whole table, so the rest are
 * counted instead.
 */
const MAX_VISIBLE_SCOPES = 3;

/** Rows per page. The backend caps `limit` at 200 and defaults to 50. */
const PAGE_SIZE = 25;

/**
 * Agent access (OAuth grants) of EVERY principal, with a kill switch.
 *
 * `/account/grants` is the self-service twin: it shows the grants of the caller only.
 * A leaked or compromised token of somebody else can therefore be killed here and
 * nowhere else. The page lists the live grants newest first, filters them by person
 * (`principalId` on the server) and revokes one grant after a confirmation.
 *
 * A row: the person (a placeholder when the server sends no name, never the id), the
 * client, the scope keys, Erstellt, Zugriff bis, Erneuerung bis and "Widerrufen". The
 * server caps every token lifetime, so there is no "never expires"; a missing time
 * shows as a dash.
 *
 * The page and the revoke control both need `admin.users`. That gate is UX only — the
 * server enforces the same permission.
 */
@Component({
  selector: 'app-admin-oauth-grants',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ConfirmDialogComponent,
    TranslatePipe,
    LocalizedDatePipe,
    AvatarComponent,
    ButtonComponent,
    ButtonGroupComponent,
    FilterSelectComponent,
    NoteComponent,
    RecordsScreenComponent,
    ScreenFiltersDirective,
    ScreenListFootDirective,
    ScreenRecordDirective,
    ScreenSearchDirective,
    SearchPillComponent,
  ],
  templateUrl: './oauth-grants.component.html',
  styleUrl: './oauth-grants.component.scss',
})
export class AdminOAuthGrantsComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly grants = signal<readonly OAuthGrantAdmin[]>([]);
  readonly total = signal(0);
  readonly offset = signal(0);
  readonly loading = signal(true);
  readonly loadError = signal(false);
  /** The rows of the records screen (§ui-kit:002257); a load error keeps what showed before. */
  readonly rows = computed<LoadState<readonly ListRow[]>>(() => {
    const rows = this.grants().map((g) => ({ id: g.id, title: g.clientId }));
    if (this.loading()) return rows.length ? { state: 'loading', previous: rows } : { state: 'loading' };
    if (this.loadError())
      return {
        state: 'error',
        message: this.i18n.translate('admin.oauthGrants.error'),
        retry: () => this.load(),
      };
    if (rows.length) return { state: 'ready', data: rows };
    return this.query()
      ? { state: 'empty', icon: 'searchOff', heading: this.i18n.translate('admin.list.noHits') }
      : { state: 'empty', icon: 'key', heading: this.i18n.translate('admin.oauthGrants.empty') };
  });

  /** The text in the search pill (§002690). The server searches it as `q` (§002691). */
  readonly searchText = signal('');
  /** The search of the last load. */
  private readonly query = signal('');
  /** The hits for the pill: the total of the server while a search is set. */
  readonly hits = computed(() => (this.query() && !this.loading() ? this.total() : null));
  /** A typed search loads page one after a short pause. */
  private readonly searchLater = debounced(() => this.runSearch());

  /** The pill changed: load again after the pause. */
  setSearch(text: string): void {
    this.searchText.set(text);
    this.searchLater();
  }

  /** Enter in the pill: load now. */
  runSearch(): void {
    this.searchLater.cancel();
    const q = this.searchText().trim();
    if (q === this.query()) return;
    this.query.set(q);
    this.offset.set(0);
    this.load();
  }

  /** The grant of a row of the records screen. */
  protected grantOf(id: string): OAuthGrantAdmin {
    return this.grants().find((g) => g.id === id)!;
  }

  /** Owner filter. An empty string means "every principal". */
  readonly principalId = signal<Uuid | ''>('');
  readonly principals = signal<AdminPrincipal[]>([]);

  readonly confirmRevoke = signal<OAuthGrantAdmin | null>(null);
  readonly revoking = signal(false);

  readonly pageSize = PAGE_SIZE;

  /** The revoke control needs the same permission as the route. UX only. */
  readonly canRevoke = computed(() => this.auth.can('admin.users'));

  /** The person filter. A principal without a name or an email gets the placeholder. */
  readonly principalOptions = computed<FilterSelectOption[]>(() => {
    const all = this.i18n.translate('admin.oauthGrants.filter.allPrincipals');
    return [
      { value: '', label: all, person: { name: all, icon: 'users' } },
      ...this.principals().map((p) => {
        const label = personLabel(p, this.i18n, { fallback: 'admin.oauthGrants.unknownOwner' });
        return { value: p.id, label, person: { name: label, principalId: p.id } };
      }),
    ];
  });

  /** The text of the person chip: "Person: Alle Personen" or "Person: <name>". */
  readonly principalChipText = computed(() => {
    const id = this.principalId();
    const hit = id ? this.principalOptions().find((o) => o.value === id) : undefined;
    return filterChipText(this.i18n.translate('admin.oauthGrants.filter.principal'), hit?.label);
  });

  readonly hasPrev = computed(() => this.offset() > 0);
  readonly hasNext = computed(() => this.offset() + this.grants().length < this.total());

  /** "1–25 of 63" — a paged list must say where it stands. */
  readonly rangeLabel = computed(() =>
    this.i18n.translate('admin.oauthGrants.range', {
      from: this.grants().length ? this.offset() + 1 : 0,
      to: this.offset() + this.grants().length,
      total: this.total(),
    }),
  );

  /**
   * Loads the grants and the persons of the owner filter. A failed person load is ignored,
   * because the owner filter is optional and the list itself still works.
   */
  constructor() {
    this.load();
    this.api.listPrincipals().subscribe({
      next: (list) => this.principals.set(list),
      error: () => {},
    });
  }

  load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api
      .listOAuthGrants({
        limit: PAGE_SIZE,
        offset: this.offset(),
        principalId: this.principalId() || null,
        q: this.query() || null,
      })
      .subscribe({
        next: (page) => {
          if (!page.items.length && this.offset() > 0) {
            this.offset.update((o) => Math.max(0, o - PAGE_SIZE));
            this.load();
            return;
          }
          this.grants.set(page.items);
          this.total.set(page.total);
          this.loading.set(false);
        },
        error: () => {
          this.loadError.set(true);
          this.loading.set(false);
        },
      });
  }

  /** A changed filter always restarts at page one. */
  setPrincipal(id: string): void {
    this.principalId.set(id as Uuid | '');
    this.offset.set(0);
    this.load();
  }

  prevPage(): void {
    if (!this.hasPrev()) return;
    this.offset.update((o) => Math.max(0, o - PAGE_SIZE));
    this.load();
  }

  nextPage(): void {
    if (!this.hasNext()) return;
    this.offset.update((o) => o + PAGE_SIZE);
    this.load();
  }

  /** Owner name, else the localized placeholder. NEVER the id. */
  ownerName(grant: OAuthGrantAdmin): string {
    return grant.principalName ?? this.i18n.translate('admin.oauthGrants.unknownOwner');
  }

  /** The email beside the name — only when it adds something to the name. */
  ownerEmail(grant: OAuthGrantAdmin): string | null {
    return grant.principalEmail && grant.principalEmail !== grant.principalName
      ? grant.principalEmail
      : null;
  }

  /** The granted scopes as single tokens. */
  scopes(grant: OAuthGrantAdmin): string[] {
    return grant.scope.split(/\s+/).filter(Boolean);
  }

  /** The scopes that get a tag. The rest are counted, not drawn. */
  visibleScopes(grant: OAuthGrantAdmin): string[] {
    return this.scopes(grant).slice(0, MAX_VISIBLE_SCOPES);
  }

  /** How many scopes the badges leave out, or 0 when they all fit. */
  hiddenScopeCount(grant: OAuthGrantAdmin): number {
    return Math.max(0, this.scopes(grant).length - MAX_VISIBLE_SCOPES);
  }

  /** The scopes the badges leave out. Screen readers read them; the title shows them. */
  hiddenScopes(grant: OAuthGrantAdmin): string[] {
    return this.scopes(grant).slice(MAX_VISIBLE_SCOPES);
  }

  askRevoke(grant: OAuthGrantAdmin): void {
    this.confirmRevoke.set(grant);
  }

  /**
   * A 404 means the grant died between the list and the click. That is the wanted end state, so the
   * page reports it and refreshes instead of failing.
   */
  doRevoke(): void {
    const grant = this.confirmRevoke();
    if (!grant || this.revoking()) return;
    this.revoking.set(true);
    this.api.revokeOAuthGrant(grant.id).subscribe({
      next: () => this.afterRevoke('admin.oauthGrants.revoked'),
      error: (err: unknown) => {
        if (errorStatus(err) === 404) {
          this.afterRevoke('admin.oauthGrants.alreadyGone');
          return;
        }
        this.revoking.set(false);
        this.toast.show(this.i18n.translate('admin.oauthGrants.revokeFailed'), 'error');
      },
    });
  }

  private afterRevoke(message: 'admin.oauthGrants.revoked' | 'admin.oauthGrants.alreadyGone'): void {
    this.revoking.set(false);
    this.confirmRevoke.set(null);
    this.toast.show(this.i18n.translate(message), 'success');
    this.load();
  }
}
