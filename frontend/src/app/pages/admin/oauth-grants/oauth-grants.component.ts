import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  AvatarComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  NoteComponent,
  PageHeaderComponent,
  SkeletonComponent,
} from '@shared/ui';
import { ButtonComponent, DialogComponent, ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, OAuthGrantAdmin } from '../admin.models';

/* A token usually carries every scope. Showing all of them wrapped each row over three
   lines and set the height of the whole table, so the rest are counted instead. */
const MAX_VISIBLE_SCOPES = 3;

/** Rows per page. The backend caps `limit` at 200 and defaults to 50. */
const PAGE_SIZE = 25;

/** HTTP status of a failed request, or 0 when the error carries none. */
function errorStatus(err: unknown): number {
  if (typeof err === 'object' && err !== null && 'status' in err) {
    const status = Number((err as { status: unknown }).status);
    return Number.isFinite(status) ? status : 0;
  }
  return 0;
}

/**
 * Agent access (OAuth grants) of EVERY principal, with a kill switch (boards
 * Admin-Agenten-Tokens, Admin-Agenten-Tokens-Dialog).
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
    TranslatePipe,
    LocalizedDatePipe,
    AvatarComponent,
    ButtonComponent,
    DialogComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    NoteComponent,
    PageHeaderComponent,
    SkeletonComponent,
  ],
  templateUrl: './oauth-grants.component.html',
  styleUrl: './oauth-grants.component.scss',
})
export class AdminOAuthGrantsComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly grants = signal<OAuthGrantAdmin[]>([]);
  readonly total = signal(0);
  readonly offset = signal(0);
  readonly loading = signal(true);
  readonly loadError = signal(false);

  /** Owner filter. An empty string means "every principal". */
  readonly principalId = signal<Uuid | ''>('');
  readonly principals = signal<AdminPrincipal[]>([]);

  readonly confirmRevoke = signal<OAuthGrantAdmin | null>(null);
  readonly revoking = signal(false);

  readonly pageSize = PAGE_SIZE;

  /** The revoke control needs the same permission as the route. UX only. */
  readonly canRevoke = computed(() => this.auth.can('admin.users'));

  /** The person filter. A principal without a name or an email gets the placeholder. */
  readonly principalOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('admin.oauthGrants.filter.allPrincipals') },
    ...this.principals().map((p) => ({
      value: p.id,
      label: p.displayName || p.email || this.i18n.translate('admin.oauthGrants.unknownOwner'),
    })),
  ]);

  /** The text of the person chip: "Person: Alle Personen" or "Person: <name>". */
  readonly principalChipText = computed(() => {
    const id = this.principalId();
    const hit = this.principalOptions().find((o) => o.value === id);
    const name = hit?.label ?? this.i18n.translate('admin.oauthGrants.filter.allPrincipals');
    return `${this.i18n.translate('admin.oauthGrants.filter.principal')}: ${name}`;
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

  constructor() {
    this.load();
    this.api.listPrincipals().subscribe({
      next: (list) => this.principals.set(list),
      error: () => {
        /* The owner filter is optional; the list itself still works. */
      },
    });
  }

  // --- reading -------------------------------------------------------------

  load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api
      .listOAuthGrants({
        limit: PAGE_SIZE,
        offset: this.offset(),
        principalId: this.principalId() || null,
      })
      .subscribe({
        next: (page) => {
          // The last row of the last page went away (a revoke): step back one page.
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

  // --- rendering -----------------------------------------------------------

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

  // --- revoke --------------------------------------------------------------

  askRevoke(grant: OAuthGrantAdmin): void {
    this.confirmRevoke.set(grant);
  }

  doRevoke(): void {
    const grant = this.confirmRevoke();
    if (!grant || this.revoking()) return;
    this.revoking.set(true);
    this.api.revokeOAuthGrant(grant.id).subscribe({
      next: () => this.afterRevoke('admin.oauthGrants.revoked'),
      error: (err: unknown) => {
        // 404 = the grant died between the list and the click. That is the wanted
        // end state, so the page reports it and refreshes instead of failing.
        if (errorStatus(err) === 404) {
          this.afterRevoke('admin.oauthGrants.alreadyGone');
          return;
        }
        this.revoking.set(false);
        this.toast.error(this.i18n.translate('admin.oauthGrants.revokeFailed'));
      },
    });
  }

  private afterRevoke(message: 'admin.oauthGrants.revoked' | 'admin.oauthGrants.alreadyGone'): void {
    this.revoking.set(false);
    this.confirmRevoke.set(null);
    this.toast.success(this.i18n.translate(message));
    this.load();
  }
}
