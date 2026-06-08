import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  DialogComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, Gremium, Role } from '../admin.models';

interface Member {
  assignmentId: string;
  name: string;
  email: string | null;
  roleLabel: string;
}

/**
 * Mitglieder eines Gremiums (#18) — eigene **Unterseite** (`/admin/gremien/:id`).
 * Tabelle der Mitglieder; »Mitglied hinzufügen« öffnet einen **Dialog** mit
 * Inline-**Typeahead**-Suche (Vorschläge direkt unter dem Feld, Klick wählt aus).
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
  ],
  template: `
    <a class="gm__back" routerLink="/admin/gremien">← {{ 'admin.gremien.title' | t }}</a>

    <header class="gm__head">
      <div>
        <h1 class="gm__title">{{ 'admin.gremien.membersOf' | t }}: {{ gremium()?.name ?? '…' }}</h1>
        <p class="gm__subtitle">{{ 'admin.gremien.membersHint' | t }}</p>
      </div>
      <app-button (click)="openAdd()">{{ 'admin.gremien.addMember' | t }}</app-button>
    </header>

    @if (members().length === 0) {
      <p class="gm__status">{{ 'admin.gremien.membersEmpty' | t }}</p>
    } @else {
      <table class="gm__table">
        <thead>
          <tr>
            <th>{{ 'admin.users.col.name' | t }}</th>
            <th>{{ 'admin.users.col.email' | t }}</th>
            <th>{{ 'admin.gremien.memberRole' | t }}</th>
            <th class="gm__th-actions">{{ 'admin.users.col.actions' | t }}</th>
          </tr>
        </thead>
        <tbody>
          @for (m of members(); track m.assignmentId) {
            <tr>
              <td>{{ m.name }}</td>
              <td>{{ m.email || '—' }}</td>
              <td><app-badge variant="primary">{{ m.roleLabel }}</app-badge></td>
              <td class="gm__th-actions">
                <app-button variant="danger" size="sm" (click)="removeMember(m.assignmentId)">
                  {{ 'admin.gremien.memberRemove' | t }}
                </app-button>
              </td>
            </tr>
          }
        </tbody>
      </table>
    }

    <!-- Mitglied hinzufügen: Dialog mit Typeahead -->
    <app-dialog
      [open]="addOpen()"
      [title]="'admin.gremien.addMember' | t"
      [closeLabel]="'admin.gremien.cancel' | t"
      (closed)="closeAdd()"
    >
      <div class="gm__add">
        <div class="gm__typeahead">
          <label class="gm__lbl" for="gm-search">{{ 'admin.gremien.memberSearch' | t }}</label>
          <input
            id="gm-search"
            class="gm__control"
            autocomplete="off"
            [placeholder]="'admin.gremien.memberSearchPlaceholder' | t"
            [ngModel]="query()"
            (ngModelChange)="onSearch($event)"
            (focus)="onSearch(query())"
          />
          @if (candidates().length) {
            <ul class="gm__suggest" role="listbox">
              @for (c of candidates(); track c.id) {
                <li>
                  <button type="button" class="gm__suggest-item" [class.gm__suggest-item--sel]="selected()?.id === c.id" (click)="pick(c)">
                    <span class="gm__suggest-name">{{ c.displayName || c.email || c.sub }}</span>
                    @if (c.email) { <span class="gm__suggest-meta">{{ c.email }}</span> }
                  </button>
                </li>
              }
            </ul>
          }
        </div>

        @if (selected(); as s) {
          <p class="gm__picked">{{ 'admin.gremien.memberPicked' | t }}: <strong>{{ s.displayName || s.email || s.sub }}</strong></p>
        }

        <app-select
          [label]="'admin.gremien.memberRole' | t"
          [placeholder]="'admin.gremien.memberRolePlaceholder' | t"
          [options]="roleOptions()"
          [ngModel]="addRoleId()"
          (ngModelChange)="addRoleId.set($event)"
          name="memberRole"
        />
      </div>
      <div dialog-footer class="gm__dialog-foot">
        <app-button variant="ghost" (click)="closeAdd()">{{ 'admin.gremien.cancel' | t }}</app-button>
        <app-button [disabled]="!selected() || !addRoleId()" (click)="addMember()">{{ 'admin.gremien.memberAdd' | t }}</app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .gm__back {
        color: var(--color-primary);
        text-decoration: none;
        font-size: var(--fs-sm);
      }
      .gm__back:hover {
        text-decoration: underline;
      }
      .gm__head {
        display: flex;
        align-items: start;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
      }
      .gm__title {
        margin: 0;
      }
      .gm__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .gm__status {
        color: var(--color-text-muted);
        padding: var(--space-4) 0;
      }
      .gm__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        overflow: hidden;
      }
      .gm__table th {
        text-align: start;
        padding: var(--space-3) var(--space-4);
        font-size: var(--fs-xs);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--color-text-muted);
        background: var(--color-surface-sunken);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .gm__table td {
        padding: var(--space-3) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .gm__th-actions {
        text-align: end;
      }
      .gm__add {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
      }
      .gm__typeahead {
        position: relative;
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      .gm__lbl {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
      }
      .gm__control {
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-surface);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
      }
      .gm__suggest {
        list-style: none;
        margin: var(--space-1) 0 0;
        padding: var(--space-1);
        max-height: 14rem;
        overflow-y: auto;
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        box-shadow: var(--shadow-sm);
      }
      .gm__suggest-item {
        display: flex;
        flex-direction: column;
        width: 100%;
        gap: 2px;
        padding: var(--space-2) var(--space-3);
        background: transparent;
        border: 0;
        border-radius: var(--radius-sm);
        cursor: pointer;
        text-align: start;
        color: var(--color-text);
      }
      .gm__suggest-item:hover,
      .gm__suggest-item--sel {
        background: var(--color-surface-sunken);
      }
      .gm__suggest-name {
        font-weight: var(--fw-medium);
      }
      .gm__suggest-meta {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .gm__picked {
        margin: 0;
        font-size: var(--fs-sm);
      }
      .gm__dialog-foot {
        display: flex;
        gap: var(--space-3);
      }
    `,
  ],
})
export class GremiumMembersComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);

  private readonly gremiumId = this.route.snapshot.paramMap.get('id') ?? '';

  readonly gremium = signal<Gremium | null>(null);
  private readonly principals = signal<AdminPrincipal[]>([]);
  private readonly roles = signal<Role[]>([]);

  readonly addOpen = signal(false);
  readonly query = signal('');
  readonly candidates = signal<AdminPrincipal[]>([]);
  readonly selected = signal<AdminPrincipal | null>(null);
  readonly addRoleId = signal('');

  readonly roleOptions = computed<SelectOption[]>(() =>
    this.roles().map((r) => ({ value: r.id, label: this.roleName(r) })),
  );

  readonly members = computed<Member[]>(() => {
    const rolesById = new Map(this.roles().map((r) => [r.id, r]));
    const out: Member[] = [];
    for (const p of this.principals()) {
      for (const a of p.assignments) {
        if (a.gremiumId === this.gremiumId) {
          const role = rolesById.get(a.roleId);
          out.push({
            assignmentId: a.id,
            name: p.displayName || p.email || p.sub,
            email: p.email ?? null,
            roleLabel: role ? this.roleName(role) : a.roleId,
          });
        }
      }
    }
    return out;
  });

  constructor() {
    this.api
      .listGremien()
      .pipe(takeUntilDestroyed())
      .subscribe((list) => this.gremium.set(list.find((g) => g.id === this.gremiumId) ?? null));
    this.api.listRoles().subscribe((r) => this.roles.set(r));
    this.refreshPrincipals();
  }

  private roleName(role: Role): string {
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  openAdd(): void {
    this.query.set('');
    this.selected.set(null);
    this.addRoleId.set('');
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
      .assignRole({ principalId: s.id, roleId, gremiumId: this.gremiumId as Uuid, validFrom: null, validUntil: null })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('admin.gremien.memberAdded'));
          this.addOpen.set(false);
          this.refreshPrincipals();
        },
        error: () => this.toast.error(this.i18n.translate('admin.gremien.memberFailed')),
      });
  }

  removeMember(assignmentId: string): void {
    this.api.revokeRole(assignmentId as Uuid).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.gremien.memberRemoved'));
        this.refreshPrincipals();
      },
      error: () => this.toast.error(this.i18n.translate('admin.gremien.memberFailed')),
    });
  }

  private refreshPrincipals(): void {
    this.api.listPrincipals('').subscribe((p) => this.principals.set(p));
  }
}
