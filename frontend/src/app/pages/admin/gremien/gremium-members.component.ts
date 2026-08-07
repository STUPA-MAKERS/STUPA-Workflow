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
  DatepickerComponent,
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
  assignmentId: string;
  name: string;
  email: string | null;
  roleLabel: string;
  term: string;
  /** Raw membership fields. The edit dialog seeds its form from them. */
  gremiumRoleId: string;
  validFrom: string;
  validUntil: string;
}

/**
 * Members of a gremium on its own subpage at `/admin/gremien/:id`.
 *
 * The table lists the members. "Add member" opens a dialog with an inline typeahead
 * search.
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
    DatepickerComponent,
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

  /** `admin.gremien` as a front-end gate for add, edit and remove. The backend stays
   *  authoritative. The value is reactive, because the principal loads asynchronously. */
  readonly canManage = computed(() => this.auth.can('admin.gremien'));

  private readonly gremiumId = this.route.snapshot.paramMap.get('id') ?? '';
  protected readonly gremiumIdRef = this.gremiumId;

  readonly gremium = signal<Gremium | null>(null);
  private readonly principalsById = signal<Map<string, AdminPrincipal>>(new Map());
  private readonly gremiumRoles = signal<GremiumRole[]>([]);
  private readonly memberships = signal<GremiumMembership[]>([]);

  readonly addOpen = signal(false);
  readonly query = signal('');
  readonly candidates = signal<AdminPrincipal[]>([]);
  readonly selected = signal<AdminPrincipal | null>(null);
  readonly addRoleId = signal('');
  readonly addFrom = signal('');
  readonly addUntil = signal('');

  readonly roleOptions = computed<SelectOption[]>(() =>
    this.gremiumRoles().map((r) => ({ value: r.id, label: this.roleName(r) })),
  );

  /** Edit dialog for one membership: the role plus the from/until window. */
  readonly editOpen = signal(false);
  readonly editMember = signal<Member | null>(null);
  readonly editRoleId = signal('');
  readonly editFrom = signal('');
  readonly editUntil = signal('');

  readonly columns = computed<ColumnDef[]>(() => {
    const cols: ColumnDef[] = [
      { key: 'name', label: this.i18n.translate('admin.users.col.name') },
      { key: 'email', label: this.i18n.translate('admin.users.col.email') },
      { key: 'roleLabel', label: this.i18n.translate('admin.gremien.memberRole') },
      { key: 'term', label: this.i18n.translate('admin.gremien.term') },
    ];
    if (this.canManage()) {
      cols.push({ key: 'actions', label: this.i18n.translate('admin.users.col.actions'), align: 'end' });
    }
    return cols;
  });
  readonly rowId = (m: unknown): string => (m as Member).assignmentId;

  readonly members = computed<Member[]>(() => {
    const rolesById = new Map(this.gremiumRoles().map((r) => [r.id, r]));
    const byId = this.principalsById();
    return this.memberships().map((m) => {
      const p = byId.get(m.principalId);
      const role = rolesById.get(m.gremiumRoleId);
      return {
        assignmentId: m.id,
        name: p ? p.displayName || p.email || p.sub : m.principalId,
        email: p?.email ?? null,
        roleLabel: role ? this.roleName(role) : m.gremiumRoleId,
        term: this.term(m),
        gremiumRoleId: m.gremiumRoleId,
        validFrom: m.validFrom ? m.validFrom.slice(0, 10) : '',
        validUntil: m.validUntil ? m.validUntil.slice(0, 10) : '',
      };
    });
  });

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
    this.refreshSubstitutes();
  }

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

  private roleName(role: GremiumRole): string {
    return role.name[this.i18n.locale()] ?? role.name['de'] ?? role.key;
  }

  private term(m: GremiumMembership): string {
    const f = m.validFrom ? m.validFrom.slice(0, 10) : '';
    const u = m.validUntil ? m.validUntil.slice(0, 10) : '';
    if (!f && !u) return '—';
    return `${f || '…'} – ${u || '…'}`;
  }

  openAdd(): void {
    this.query.set('');
    this.selected.set(null);
    this.addRoleId.set('');
    this.addFrom.set('');
    this.addUntil.set('');
    this.candidates.set([]);
    this.addOpen.set(true);
  }

  closeAdd(): void {
    this.addOpen.set(false);
  }

  onSearch(q: string): void {
    this.query.set(q);
    this.api.listPrincipals(q).subscribe({
      next: (list) => this.candidates.set(list.slice(0, 8)),
      error: () => this.candidates.set([]),
    });
  }

  pick(c: AdminPrincipal): void {
    this.selected.set(c);
    this.query.set(c.displayName || c.email || c.sub);
    this.candidates.set([]);
  }

  addMember(): void {
    const s = this.selected();
    const roleId = this.addRoleId();
    if (!s || !roleId) return;
    this.api
      .createGremiumMembership(this.gremiumId as Uuid, {
        principalId: s.id,
        gremiumRoleId: roleId as Uuid,
        validFrom: this.addFrom() || null,
        validUntil: this.addUntil() || null,
      })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('admin.gremien.memberAdded'));
          this.addOpen.set(false);
          this.refresh();
        },
        // 409 means an overlapping term. A member holds one role per point in time.
        // 422 means validFrom is not before validUntil.
        error: (err: { status?: number }) =>
          this.toast.error(this.i18n.translate(this.memberErrorKey(err.status))),
      });
  }

  /** Open the edit dialog for one membership. The member and the Gremium stay fixed —
   *  only the role and the term of office change. */
  openEdit(m: Member): void {
    this.editMember.set(m);
    this.editRoleId.set(m.gremiumRoleId);
    this.editFrom.set(m.validFrom);
    this.editUntil.set(m.validUntil);
    this.editOpen.set(true);
  }

  closeEdit(): void {
    this.editOpen.set(false);
    this.editMember.set(null);
  }

  saveEdit(): void {
    const m = this.editMember();
    const roleId = this.editRoleId();
    if (!m || !roleId) return;
    this.api
      .updateGremiumMembership(m.assignmentId as Uuid, {
        gremiumRoleId: roleId as Uuid,
        validFrom: this.editFrom() || null,
        validUntil: this.editUntil() || null,
      })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('admin.gremien.memberSaved'));
          this.closeEdit();
          this.refresh();
        },
        // 409 = the term overlaps another term of this member. 422 = validFrom is not
        // before validUntil. Both need their own words, not a generic failure.
        error: (err: { status?: number }) =>
          this.toast.error(this.i18n.translate(this.memberErrorKey(err.status))),
      });
  }

  private memberErrorKey(status: number | undefined): TranslationKey {
    if (status === 409) return 'admin.gremien.memberOverlap';
    if (status === 422) return 'admin.gremien.memberBadTerm';
    return 'admin.gremien.memberFailed';
  }

  removeMember(membershipId: string): void {
    this.api.deleteGremiumMembership(membershipId as Uuid).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.gremien.memberRemoved'));
        this.refresh();
      },
      error: () => this.toast.error(this.i18n.translate('admin.gremien.memberFailed')),
    });
  }

  private refresh(): void {
    this.api.listGremiumMemberships(this.gremiumId as Uuid).subscribe({
      next: (m) => this.memberships.set(m),
      // Do not swallow the error. Show a 403 or another failure, not an empty table.
      error: () => {
        this.memberships.set([]);
        this.toast.error(this.i18n.translate('admin.gremien.membersLoadFailed'));
      },
    });
  }
}
