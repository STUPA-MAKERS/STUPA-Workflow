import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  type OnInit,
  output,
  signal,
} from '@angular/core';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import { SkeletonComponent } from '@shared/ui';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import {
  GREMIUM_PERMISSIONS,
  type GremiumMembershipMapping,
  type GremiumRole,
  type GremiumRoleMapping,
  MEMBER_GREMIUM_ROLE_KEY,
  sortGremiumRoles,
} from '../admin.models';
import { GremiumRoleDialogComponent } from './gremium-role-dialog.component';

let nextId = 0;

/**
 * The roles of one gremium and their rights as a matrix (boards Verwaltung-Gremium-Dialog
 * background and Verwaltung-Gremiumrolle-Dialog).
 *
 * One row per role: the name, "Pflichtrolle" for a forced role, the OIDC groups that give
 * the role (from the gremium role mappings; for `member` the membership groups), one box
 * per right of the fixed catalogue (O7, "Protokoll freigeben" included) and the actions.
 * A box saves at once. In a narrow container the header goes away and the boxes become
 * chips with their names under the role.
 *
 * - Edit and delete need `admin.gremium_roles`; without it the matrix is read-only.
 * - The group lines need `admin.group_mappings`; without it they do not show.
 * - A forced role cannot be deleted (the server answers 409); a role that a membership or
 *   a group mapping uses cannot be deleted either (409, named in the toast).
 */
@Component({
  selector: 'app-gremium-role-matrix',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    CapitalizePipe,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    SkeletonComponent,
    GremiumRoleDialogComponent,
  ],
  templateUrl: './gremium-role-matrix.component.html',
  styleUrl: './gremium-role-matrix.component.scss',
})
export class GremiumRoleMatrixComponent implements OnInit {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly gremiumId = input.required<Uuid>();
  readonly gremiumName = input('');
  /** Show the section heading (the gremien page). The roles page has its own title. */
  readonly heading = input(true);
  /** The row surface: 2 on a page, 3 inside a gremium row on surface 2. */
  readonly surface = input<2 | 3>(2);
  /** The number of roles after a create or a delete. */
  readonly countChange = output<number>();

  protected readonly uid = `rm-${nextId++}`;
  protected readonly permissions = GREMIUM_PERMISSIONS;
  protected readonly canEdit = computed(() => this.auth.can('admin.gremium_roles'));
  protected readonly canGroups = computed(() => this.auth.can('admin.group_mappings'));

  protected readonly loading = signal(true);
  protected readonly failed = signal(false);
  private readonly roles = signal<GremiumRole[]>([]);
  private readonly roleMappings = signal<GremiumRoleMapping[]>([]);
  private readonly membershipMappings = signal<GremiumMembershipMapping[]>([]);
  /** The ids of the roles with a save in flight: their boxes wait. */
  protected readonly busy = signal<ReadonlySet<string>>(new Set());

  /** The dialog: `undefined` = closed, `null` = a new role, else the role to edit. */
  protected readonly dialogRole = signal<GremiumRole | null | undefined>(undefined);
  /** The last role of the dialog. It stays while the dialog closes. */
  protected readonly lastDialogRole = signal<GremiumRole | null>(null);
  protected readonly confirmDelete = signal<GremiumRole | null>(null);
  protected readonly deleting = signal(false);

  protected readonly sorted = computed(() => sortGremiumRoles(this.roles(), (r) => this.label(r)));

  ngOnInit(): void {
    this.load();
  }

  private load(): void {
    const id = this.gremiumId();
    this.loading.set(true);
    this.failed.set(false);
    this.api.listGremiumRoles(id, { quiet: true }).subscribe({
      next: (r) => {
        this.roles.set(r);
        this.loading.set(false);
      },
      error: () => {
        this.failed.set(true);
        this.loading.set(false);
      },
    });
    if (this.canGroups()) {
      // The group lines are extra information. A failed read leaves them out.
      this.api.listRoleMappings().subscribe({
        next: (m) => this.roleMappings.set(m.filter((x) => x.gremiumId === id)),
        error: () => this.roleMappings.set([]),
      });
      this.api.listMembershipMappings().subscribe({
        next: (m) => this.membershipMappings.set(m.filter((x) => x.gremiumId === id)),
        error: () => this.membershipMappings.set([]),
      });
    }
  }

  protected label(r: GremiumRole): string {
    return r.name[this.i18n.locale()] ?? r.name['de'] ?? r.key;
  }

  protected permLabel(p: string): TranslationKey {
    return `admin.gremiumPerm.${p}` as TranslationKey;
  }

  /** The part of a permission key before its dot (`protocol` of `protocol.finalize`). */
  protected keyHead(p: string): string {
    return p.split('.')[0];
  }

  /** The part of a permission key after its dot (`finalize` of `protocol.finalize`). */
  protected keyTail(p: string): string {
    return p.split('.').slice(1).join('.');
  }

  protected has(r: GremiumRole, p: string): boolean {
    return (r.permissions ?? []).includes(p);
  }

  protected isMember(r: GremiumRole): boolean {
    return r.key === MEMBER_GREMIUM_ROLE_KEY;
  }

  /** The OIDC groups that give the role. For `member`: the groups that give membership. */
  protected groupsOf(r: GremiumRole | null): string[] {
    if (!r) return [];
    if (this.isMember(r)) return this.membershipMappings().map((m) => m.oidcGroup);
    return this.roleMappings()
      .filter((m) => m.gremiumRoleId === r.id)
      .map((m) => m.oidcGroup);
  }

  /** A box saves the new rights of its role at once; a failure puts the box back. */
  protected toggle(r: GremiumRole, p: string, event: Event): void {
    const box = event.target as HTMLInputElement;
    const on = box.checked;
    if (!this.canEdit() || this.busy().has(r.id)) return;
    const before = [...(r.permissions ?? [])];
    const set = new Set(before);
    if (on) set.add(p);
    else set.delete(p);
    const permissions = GREMIUM_PERMISSIONS.filter((x) => set.has(x));
    this.replace({ ...r, permissions });
    this.busy.update((b) => new Set(b).add(r.id));
    this.api.updateGremiumRole(r.id, { permissions }).subscribe({
      next: (saved) => {
        this.done(r.id);
        this.replace(saved);
      },
      error: () => {
        this.done(r.id);
        this.replace({ ...r, permissions: before });
        // The box shows the old state again, also when the binding did not change.
        box.checked = !on;
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  private done(id: string): void {
    this.busy.update((b) => {
      const next = new Set(b);
      next.delete(id);
      return next;
    });
  }

  private replace(role: GremiumRole): void {
    this.roles.update((list) => list.map((x) => (x.id === role.id ? role : x)));
  }

  protected openAdd(): void {
    this.lastDialogRole.set(null);
    this.dialogRole.set(null);
  }

  protected openEdit(r: GremiumRole): void {
    this.lastDialogRole.set(r);
    this.dialogRole.set(r);
  }

  protected closeDialog(): void {
    this.dialogRole.set(undefined);
  }

  protected onSaved(saved: GremiumRole): void {
    const isNew = !this.roles().some((r) => r.id === saved.id);
    if (isNew) {
      this.roles.update((list) => [...list, saved]);
      this.countChange.emit(this.roles().length);
    } else {
      this.replace(saved);
    }
    this.dialogRole.set(undefined);
    this.toast.success(this.i18n.translate('admin.gremiumRoles.saved'));
  }

  protected askDelete(r: GremiumRole): void {
    if (r.forced) return;
    this.dialogRole.set(undefined);
    this.confirmDelete.set(r);
  }

  protected doDelete(): void {
    const r = this.confirmDelete();
    if (!r || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteGremiumRole(r.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(null);
        this.roles.update((list) => list.filter((x) => x.id !== r.id));
        this.countChange.emit(this.roles().length);
        this.toast.success(this.i18n.translate('admin.gremiumRoles.deleted'));
      },
      error: (err: { status?: number }) => {
        this.deleting.set(false);
        this.toast.error(
          this.i18n.translate(
            err.status === 409 ? 'admin.gremiumRoles.inUse' : 'admin.gremiumRoles.deleteFailed',
          ),
        );
      },
    });
  }
}
