import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { type DelegationSubstitute, DelegationsApiService } from '@core/api/delegations.service';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, Gremium, GremiumMembership, GremiumRole } from '../admin.models';

interface Member {
  id: string;
  name: string;
  email: string | null;
  roleLabel: string;
}

/**
 * Members of a gremium on its own subpage at `/admin/gremien/:id`.
 *
 * The members come only from the OIDC groups of the IdP, so the member table is
 * read-only. The OIDC group mappings live on `/admin/group-mappings`. The backend
 * syncs the memberships at each login and after each mapping change.
 */
@Component({
  selector: 'app-gremium-members',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    BadgeComponent,
    SelectComponent,
    DialogComponent,
    DataTableComponent,
    CellDirective,
    IconComponent,
    PageHeaderComponent,
  ],
  templateUrl: './gremium-members.component.html',
  styleUrl: './gremium-members.component.scss',
})
export class GremiumMembersComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);

  /**
   * True until the first answer. Without it the table shows its empty text while the
   * request is still out, which asserts there is nothing when nothing has arrived yet.
   */
  protected readonly loading = signal(true);

  /** The hint links to the mappings page only with its permission. The value is
   *  reactive, because the principal loads asynchronously. */
  protected readonly canManageMappings = computed(() => this.auth.can('admin.group_mappings'));

  private readonly gremiumId = this.route.snapshot.paramMap.get('id') ?? '';

  readonly gremium = signal<Gremium | null>(null);
  private readonly principalsById = signal<Map<string, AdminPrincipal>>(new Map());
  private readonly gremiumRoles = signal<GremiumRole[]>([]);
  private readonly memberships = signal<GremiumMembership[]>([]);

  private readonly rolesById = computed(
    () => new Map(this.gremiumRoles().map((r) => [r.id, r])),
  );

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.users.col.name'), card: 'title' },
    { key: 'email', label: this.i18n.translate('admin.users.col.email') },
    { key: 'roleLabel', label: this.i18n.translate('admin.gremien.memberRole') },
  ]);
  readonly rowId = (m: unknown): string => (m as Member).id;

  readonly members = computed<Member[]>(() => {
    const byId = this.principalsById();
    return this.memberships().map((m) => {
      const p = byId.get(m.principalId);
      return {
        id: m.id,
        name: p ? p.displayName || p.email || p.sub : m.principalId,
        email: p?.email ?? null,
        roleLabel: this.roleLabel(m.gremiumRoleId),
      };
    });
  });

  // --- substitute pool -------------------------------------------------------

  private readonly delegationsApi = inject(DelegationsApiService);
  readonly substitutes = signal<DelegationSubstitute[]>([]);
  readonly addSubOpen = signal(false);
  readonly subQuery = signal('');
  readonly subCandidates = signal<AdminPrincipal[]>([]);
  readonly subSelected = signal<AdminPrincipal | null>(null);
  /** An empty value makes a gremium-wide substitute that represents every member. */
  readonly subMemberId = signal('');

  readonly subColumns = computed<ColumnDef[]>(() => [
    {
      key: 'substitute',
      label: this.i18n.translate('admin.substitutes.col.substitute'),
      card: 'title',
    },
    { key: 'member', label: this.i18n.translate('admin.substitutes.col.member') },
    { key: 'actions', label: this.i18n.translate('admin.users.col.actions'), align: 'end' },
  ]);
  readonly subRowId = (s: unknown): string => (s as DelegationSubstitute).id;

  /** Options for "represents": all members or one specific member. */
  readonly memberOptions = computed<SelectOption[]>(() => {
    const byId = this.principalsById();
    const seen = new Set<string>();
    const opts: SelectOption[] = [
      { value: '', label: this.i18n.translate('admin.substitutes.allMembers') },
    ];
    for (const m of this.memberships()) {
      if (seen.has(m.principalId)) continue;
      seen.add(m.principalId);
      const p = byId.get(m.principalId);
      opts.push({ value: m.principalId, label: p ? p.displayName || p.email || p.sub : m.principalId });
    }
    return opts;
  });

  constructor() {
    this.api
      .listGremien()
      .pipe(takeUntilDestroyed())
      .subscribe((list) => this.gremium.set(list.find((g) => g.id === this.gremiumId) ?? null));
    this.api.listGremiumRoles(this.gremiumId as Uuid).subscribe({
      next: (r) => this.gremiumRoles.set(r),
      error: () => this.gremiumRoles.set([]),
    });
    this.api.listPrincipals('').subscribe({
      next: (p) => this.principalsById.set(new Map(p.map((x) => [x.id, x]))),
      error: () => this.principalsById.set(new Map()),
    });
    this.refresh();
    this.refreshSubstitutes();
  }

  private roleName(role: GremiumRole): string {
    return role.name[this.i18n.locale()] ?? role.name['de'] ?? role.key;
  }

  private roleLabel(roleId: string): string {
    const role = this.rolesById().get(roleId);
    return role ? this.roleName(role) : roleId;
  }

  // --- substitute pool -------------------------------------------------------

  openAddSub(): void {
    this.subQuery.set('');
    this.subSelected.set(null);
    this.subCandidates.set([]);
    this.subMemberId.set('');
    this.addSubOpen.set(true);
  }

  onSubSearch(q: string): void {
    this.subQuery.set(q);
    this.api.listPrincipals(q).subscribe({
      next: (list) => this.subCandidates.set(list.slice(0, 8)),
      error: () => this.subCandidates.set([]),
    });
  }

  pickSub(c: AdminPrincipal): void {
    this.subSelected.set(c);
    this.subQuery.set(c.displayName || c.email || c.sub);
    this.subCandidates.set([]);
  }

  addSub(): void {
    const s = this.subSelected();
    if (!s) return;
    this.delegationsApi
      .addSubstitute({
        gremiumId: this.gremiumId as Uuid,
        memberId: this.subMemberId() ? (this.subMemberId() as Uuid) : null,
        substituteId: s.id,
      })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('admin.substitutes.added'));
          this.addSubOpen.set(false);
          this.refreshSubstitutes();
        },
        error: (err: { status?: number }) =>
          this.toast.error(
            this.i18n.translate(
              err.status === 409 ? 'admin.substitutes.duplicate' : 'admin.substitutes.failed',
            ),
          ),
      });
  }

  removeSub(id: string): void {
    this.delegationsApi.removeSubstitute(id as Uuid).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.substitutes.removed'));
        this.refreshSubstitutes();
      },
      error: () => this.toast.error(this.i18n.translate('admin.substitutes.failed')),
    });
  }

  private refreshSubstitutes(): void {
    this.delegationsApi.substitutes(this.gremiumId as Uuid).subscribe({
      next: (list) => this.substitutes.set(list),
      error: () => this.substitutes.set([]),
    });
  }

  private refresh(): void {
    this.loading.set(true);
    this.api.listGremiumMemberships(this.gremiumId as Uuid).subscribe({
      next: (m) => {
        this.memberships.set(m);
        this.loading.set(false);
      },
      // Do not swallow the error. Show a 403 or another failure, not an empty table.
      error: () => {
        this.memberships.set([]);
        this.loading.set(false);
        this.toast.error(this.i18n.translate('admin.gremien.membersLoadFailed'));
      },
    });
  }
}
