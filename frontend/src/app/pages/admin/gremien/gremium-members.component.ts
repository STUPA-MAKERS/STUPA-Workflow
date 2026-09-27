import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
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
import type {
  AdminPrincipal,
  Gremium,
  GremiumGroupMapping,
  GremiumMembership,
  GremiumRole,
} from '../admin.models';

interface Member {
  id: string;
  name: string;
  email: string | null;
  roleLabel: string;
}

interface MappingRow {
  id: string;
  oidcGroup: string;
  roleLabel: string;
}

/** The RBAC resolver reserves this group prefix. The backend refuses it with 422. */
const RESERVED_GROUP_PREFIX = 'vote:';

/**
 * Members of a gremium on its own subpage at `/admin/gremien/:id`.
 *
 * The members come only from the OIDC groups of the IdP, so the member table is
 * read-only. The admin maps an OIDC group to a gremium role here. The backend syncs
 * the memberships at each login and after each mapping change.
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
  protected readonly mappingsLoading = signal(true);

  /** `admin.gremien` as a front-end gate for the mapping controls. The backend stays
   *  authoritative. The value is reactive, because the principal loads asynchronously. */
  readonly canManage = computed(() => this.auth.can('admin.gremien'));

  private readonly gremiumId = this.route.snapshot.paramMap.get('id') ?? '';
  protected readonly gremiumIdRef = this.gremiumId;

  readonly gremium = signal<Gremium | null>(null);
  private readonly principalsById = signal<Map<string, AdminPrincipal>>(new Map());
  private readonly gremiumRoles = signal<GremiumRole[]>([]);
  private readonly memberships = signal<GremiumMembership[]>([]);
  private readonly mappings = signal<GremiumGroupMapping[]>([]);

  private readonly rolesById = computed(
    () => new Map(this.gremiumRoles().map((r) => [r.id, r])),
  );

  readonly roleOptions = computed<SelectOption[]>(() =>
    this.gremiumRoles().map((r) => ({ value: r.id, label: this.roleName(r) })),
  );

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.users.col.name') },
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

  // --- OIDC group mappings ---------------------------------------------------

  readonly mappingColumns = computed<ColumnDef[]>(() => {
    const cols: ColumnDef[] = [
      { key: 'oidcGroup', label: this.i18n.translate('admin.groupMappings.oidcGroup') },
      { key: 'roleLabel', label: this.i18n.translate('admin.gremien.memberRole') },
    ];
    if (this.canManage()) {
      cols.push({ key: 'actions', label: this.i18n.translate('admin.users.col.actions'), align: 'end' });
    }
    return cols;
  });
  readonly mappingRowId = (r: unknown): string => (r as MappingRow).id;

  readonly mappingRows = computed<MappingRow[]>(() =>
    this.mappings().map((m) => ({
      id: m.id,
      oidcGroup: m.oidcGroup,
      roleLabel: this.roleLabel(m.gremiumRoleId),
    })),
  );

  readonly mappingOpen = signal(false);
  /** null = the dialog creates a new mapping. */
  readonly mappingEditId = signal<string | null>(null);
  readonly mappingGroup = signal('');
  readonly mappingRoleId = signal('');
  readonly mappingSaving = signal(false);
  readonly mappingDeleteId = signal<string | null>(null);

  /** The group name uses the reserved prefix. The dialog says so before the 422. */
  readonly mappingGroupReserved = computed(() =>
    this.mappingGroup().trim().startsWith(RESERVED_GROUP_PREFIX),
  );
  readonly mappingValid = computed(
    () => !!this.mappingGroup().trim() && !this.mappingGroupReserved() && !!this.mappingRoleId(),
  );

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
    { key: 'substitute', label: this.i18n.translate('admin.substitutes.col.substitute') },
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
    this.refreshMappings();
    this.refreshSubstitutes();
  }

  private roleName(role: GremiumRole): string {
    return role.name[this.i18n.locale()] ?? role.name['de'] ?? role.key;
  }

  private roleLabel(roleId: string): string {
    const role = this.rolesById().get(roleId);
    return role ? this.roleName(role) : roleId;
  }

  // --- mapping dialog ----------------------------------------------------------

  openAddMapping(): void {
    this.mappingEditId.set(null);
    this.mappingGroup.set('');
    this.mappingRoleId.set('');
    this.mappingOpen.set(true);
  }

  openEditMapping(id: string): void {
    const m = this.mappings().find((x) => x.id === id);
    if (!m) return;
    this.mappingEditId.set(id);
    this.mappingGroup.set(m.oidcGroup);
    this.mappingRoleId.set(m.gremiumRoleId);
    this.mappingOpen.set(true);
  }

  closeMapping(): void {
    this.mappingOpen.set(false);
  }

  saveMapping(): void {
    if (!this.mappingValid() || this.mappingSaving()) return;
    const body = { oidcGroup: this.mappingGroup().trim(), gremiumRoleId: this.mappingRoleId() as Uuid };
    const id = this.mappingEditId();
    const req = id
      ? this.api.updateGremiumGroupMapping(id as Uuid, body)
      : this.api.createGremiumGroupMapping(this.gremiumId as Uuid, body);
    this.mappingSaving.set(true);
    req.subscribe({
      next: () => {
        this.mappingSaving.set(false);
        this.toast.success(this.i18n.translate('admin.gremien.mappingSaved'));
        this.mappingOpen.set(false);
        this.afterMappingChange();
      },
      // The dialog stays open, so the admin can correct the group or the role.
      error: (err: { status?: number }) => {
        this.mappingSaving.set(false);
        this.toast.error(this.i18n.translate(this.mappingErrorKey(err.status)));
      },
    });
  }

  removeMapping(): void {
    const id = this.mappingDeleteId();
    if (!id) return;
    this.api.deleteGremiumGroupMapping(id as Uuid).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.gremien.mappingDeleted'));
        this.mappingDeleteId.set(null);
        this.afterMappingChange();
      },
      error: () => this.toast.error(this.i18n.translate('admin.gremien.mappingFailed')),
    });
  }

  private mappingErrorKey(status: number | undefined): TranslationKey {
    if (status === 409) return 'admin.gremien.mappingConflict';
    if (status === 422) return 'admin.gremien.mappingInvalid';
    return 'admin.gremien.mappingFailed';
  }

  /** The backend re-syncs the memberships on each mapping change. Show the result. */
  private afterMappingChange(): void {
    this.refreshMappings();
    this.refresh();
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

  private refreshMappings(): void {
    this.mappingsLoading.set(true);
    this.api.listGremiumGroupMappings(this.gremiumId as Uuid).subscribe({
      next: (m) => {
        this.mappings.set(m);
        this.mappingsLoading.set(false);
      },
      error: () => {
        this.mappings.set([]);
        this.mappingsLoading.set(false);
        this.toast.error(this.i18n.translate('admin.gremien.mappingsLoadFailed'));
      },
    });
  }
}
