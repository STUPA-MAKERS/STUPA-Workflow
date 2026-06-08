import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { CardComponent } from '@shared/ui/card/card.component';
import { BadgeComponent, SelectComponent, type SelectOption } from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminApiService } from '../admin-api.service';
import type {
  AdminPrincipal,
  Gremium,
  GremiumCreateBody,
  GremiumUpdateBody,
  Role,
} from '../admin.models';

/** Eine Mitgliedschaft (Rollenzuweisung) innerhalb eines Gremiums (#11). */
interface GremiumMember {
  assignmentId: string;
  principalId: string;
  name: string;
  email: string | null;
  roleLabel: string;
}

/** Editier-Formularzustand eines Gremiums (flach). */
interface GremiumForm {
  name: string;
  slug: string;
  cdVariant: string;
  defaultLang: string;
}

function emptyForm(): GremiumForm {
  return { name: '', slug: '', cdVariant: 'stupa', defaultLang: 'de' };
}

/**
 * Gremien-Verwaltung (#105). Schließt die Lücke: das Backend bietet volle
 * Gremien-CRUD (`GET/POST/PATCH /admin/gremien`, P `admin.config`), aber im
 * Frontend fehlte der Ort zum Anlegen/Bearbeiten — obwohl Gremien überall als
 * Pflicht-Fremdschlüssel referenziert sind (Sitzung, Budget-Topf, Antragstyp).
 * Folgt dem Budget-Töpfe-Muster (`/budget/pots`): Anlege-Formular + Liste +
 * „Bearbeiten", durchgängig custom-Controls.
 */
@Component({
  selector: 'app-admin-gremien',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CardComponent, SelectComponent, BadgeComponent],
  template: `
    <header class="grem__head">
      <h1 class="grem__title">{{ 'admin.gremien.title' | t }}</h1>
      <p class="grem__subtitle">{{ 'admin.gremien.subtitle' | t }}</p>
    </header>

    <app-card [heading]="(editingId() ? 'admin.gremien.edit' : 'admin.gremien.create') | t">
      <form class="grem__form" (submit)="submit($event)">
        <div class="grem__grid">
          <div class="field">
            <label class="field__label" for="grem-name">{{ 'admin.gremien.name' | t }}</label>
            <input
              id="grem-name"
              class="field__control"
              name="name"
              [ngModel]="form().name"
              (ngModelChange)="patch('name', $event)"
              required
            />
          </div>
          <div class="field">
            <label class="field__label" for="grem-slug">{{ 'admin.gremien.slug' | t }}</label>
            <input
              id="grem-slug"
              class="field__control"
              name="slug"
              [placeholder]="'admin.gremien.slugPlaceholder' | t"
              [ngModel]="form().slug"
              (ngModelChange)="patch('slug', $event)"
              required
            />
          </div>
          <div class="field">
            <label class="field__label" for="grem-cd">{{ 'admin.gremien.cdVariant' | t }}</label>
            <input
              id="grem-cd"
              class="field__control"
              name="cdVariant"
              [placeholder]="'admin.gremien.cdVariantPlaceholder' | t"
              [ngModel]="form().cdVariant"
              (ngModelChange)="patch('cdVariant', $event)"
            />
          </div>
          <app-select
            name="defaultLang"
            [label]="'admin.gremien.defaultLang' | t"
            [options]="langOptions()"
            [ngModel]="form().defaultLang"
            (ngModelChange)="patch('defaultLang', $event)"
          />
        </div>

        <div class="grem__actions">
          <app-button type="submit" size="sm" [disabled]="!canSubmit()" [loading]="saving()">
            {{ (editingId() ? 'admin.gremien.save' : 'admin.gremien.add') | t }}
          </app-button>
          @if (editingId()) {
            <app-button type="button" variant="ghost" size="sm" (click)="cancelEdit()">
              {{ 'admin.gremien.cancel' | t }}
            </app-button>
          }
        </div>
      </form>
    </app-card>

    <section class="grem__list" [attr.aria-label]="'admin.gremien.title' | t">
      @if (loading()) {
        <p class="grem__status" aria-live="polite">{{ 'admin.gremien.loading' | t }}</p>
      } @else if (loadError()) {
        <p class="grem__status grem__status--error" role="alert">{{ 'admin.gremien.error' | t }}</p>
      } @else if (!gremien().length) {
        <p class="grem__status">{{ 'admin.gremien.empty' | t }}</p>
      } @else {
        <table class="grem__table">
          <thead>
            <tr>
              <th>{{ 'admin.gremien.name' | t }}</th>
              <th>{{ 'admin.gremien.slug' | t }}</th>
              <th>{{ 'admin.gremien.cdVariant' | t }}</th>
              <th>{{ 'admin.gremien.defaultLang' | t }}</th>
              <th class="grem__th-actions">{{ 'admin.gremien.actions' | t }}</th>
            </tr>
          </thead>
          <tbody>
            @for (g of gremien(); track g.id) {
              <tr [class.grem__row--editing]="editingId() === g.id">
                <td>{{ g.name }}</td>
                <td>{{ g.slug }}</td>
                <td>{{ g.cdVariant }}</td>
                <td>{{ g.defaultLang }}</td>
                <td class="grem__th-actions">
                  <app-button variant="ghost" size="sm" (click)="openMembers(g)">
                    {{ 'admin.gremien.members' | t }}
                  </app-button>
                  <app-button variant="secondary" size="sm" (click)="startEdit(g)">
                    {{ 'admin.gremien.editAction' | t }}
                  </app-button>
                </td>
              </tr>
            }
          </tbody>
        </table>
      }
    </section>

    <!-- Mitglieder eines Gremiums verwalten (#11) -->
    @if (selectedGremium(); as g) {
      <app-card [heading]="('admin.gremien.membersOf' | t) + ': ' + g.name">
        <div class="grem__members-head">
          <p class="grem__subtitle">{{ 'admin.gremien.membersHint' | t }}</p>
          <app-button variant="ghost" size="sm" (click)="closeMembers()">{{ 'admin.gremien.membersClose' | t }}</app-button>
        </div>

        <!-- Mitglied hinzufügen -->
        <form class="grem__add-member" (submit)="addMember($event)">
          <div class="field">
            <label class="field__label" for="member-search">{{ 'admin.gremien.memberSearch' | t }}</label>
            <input
              id="member-search"
              class="field__control"
              name="memberSearch"
              [placeholder]="'admin.gremien.memberSearchPlaceholder' | t"
              [ngModel]="memberQuery()"
              (ngModelChange)="onMemberSearch($event)"
            />
          </div>
          <app-select
            name="memberPrincipal"
            [label]="'admin.gremien.memberPrincipal' | t"
            [placeholder]="'admin.gremien.memberPrincipalPlaceholder' | t"
            [options]="candidateOptions()"
            [ngModel]="addPrincipalId()"
            (ngModelChange)="addPrincipalId.set($event)"
          />
          <app-select
            name="memberRole"
            [label]="'admin.gremien.memberRole' | t"
            [placeholder]="'admin.gremien.memberRolePlaceholder' | t"
            [options]="roleOptions()"
            [ngModel]="addRoleId()"
            (ngModelChange)="addRoleId.set($event)"
          />
          <app-button type="submit" size="sm" [disabled]="!addPrincipalId() || !addRoleId()">
            {{ 'admin.gremien.memberAdd' | t }}
          </app-button>
        </form>

        @if (members().length === 0) {
          <p class="grem__status">{{ 'admin.gremien.membersEmpty' | t }}</p>
        } @else {
          <table class="grem__table">
            <thead>
              <tr>
                <th>{{ 'admin.users.col.name' | t }}</th>
                <th>{{ 'admin.users.col.email' | t }}</th>
                <th>{{ 'admin.gremien.memberRole' | t }}</th>
                <th class="grem__th-actions">{{ 'admin.users.col.actions' | t }}</th>
              </tr>
            </thead>
            <tbody>
              @for (m of members(); track m.assignmentId) {
                <tr>
                  <td>{{ m.name }}</td>
                  <td>{{ m.email || '—' }}</td>
                  <td><app-badge variant="primary">{{ m.roleLabel }}</app-badge></td>
                  <td class="grem__th-actions">
                    <app-button variant="danger" size="sm" (click)="removeMember(m.assignmentId)">
                      {{ 'admin.gremien.memberRemove' | t }}
                    </app-button>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
      </app-card>
    }
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .grem__title {
        margin: 0;
      }
      .grem__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .grem__grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
        gap: var(--space-4);
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .field__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
      }
      .field__control {
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-surface);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
      }
      .field__control:focus-visible {
        outline: 2px solid var(--color-primary);
        outline-offset: 1px;
      }
      .grem__actions {
        display: flex;
        gap: var(--space-2);
        margin-top: var(--space-4);
      }
      .grem__status {
        color: var(--color-text-muted);
        padding: var(--space-4) 0;
      }
      .grem__status--error {
        color: var(--color-danger);
      }
      .grem__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-md);
      }
      .grem__table th,
      .grem__table td {
        text-align: left;
        padding: var(--space-3);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .grem__th-actions {
        text-align: right;
      }
      .grem__row--editing {
        background: var(--color-primary-subtle);
      }
      .grem__members-head {
        display: flex;
        justify-content: space-between;
        align-items: start;
        gap: var(--space-3);
        flex-wrap: wrap;
        margin-bottom: var(--space-4);
      }
      .grem__add-member {
        display: flex;
        flex-wrap: wrap;
        align-items: end;
        gap: var(--space-3);
        margin-bottom: var(--space-4);
        padding-bottom: var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .grem__add-member .field {
        flex: 1 1 12rem;
      }
    `,
  ],
})
export class AdminGremienComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly gremien = signal<Gremium[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal(false);
  readonly saving = signal(false);
  readonly editingId = signal<Uuid | null>(null);
  readonly form = signal<GremiumForm>(emptyForm());

  readonly langOptions = computed<SelectOption[]>(() => [
    { value: 'de', label: this.i18n.translate('admin.gremien.langDe') },
    { value: 'en', label: this.i18n.translate('admin.gremien.langEn') },
  ]);

  readonly canSubmit = computed(() => {
    const f = this.form();
    return f.name.trim().length > 0 && f.slug.trim().length > 0 && !this.saving();
  });

  // --- Mitglieder-Verwaltung (#11) -----------------------------------------
  private readonly principals = signal<AdminPrincipal[]>([]);
  private readonly memberRoles = signal<Role[]>([]);
  readonly selectedGremium = signal<Gremium | null>(null);
  readonly memberQuery = signal('');
  readonly candidates = signal<AdminPrincipal[]>([]);
  readonly addPrincipalId = signal('');
  readonly addRoleId = signal('');

  readonly roleOptions = computed<SelectOption[]>(() =>
    this.memberRoles().map((r) => ({ value: r.id, label: this.roleName(r) })),
  );
  readonly candidateOptions = computed<SelectOption[]>(() =>
    this.candidates().map((p) => ({ value: p.id, label: p.displayName || p.email || p.sub })),
  );

  readonly members = computed<GremiumMember[]>(() => {
    const g = this.selectedGremium();
    if (!g) return [];
    const rolesById = new Map(this.memberRoles().map((r) => [r.id, r]));
    const out: GremiumMember[] = [];
    for (const p of this.principals()) {
      for (const a of p.assignments) {
        if (a.gremiumId === g.id) {
          const role = rolesById.get(a.roleId);
          out.push({
            assignmentId: a.id,
            principalId: p.id,
            name: p.displayName || p.email || p.sub,
            email: p.email ?? null,
            roleLabel: role ? this.roleName(role) : a.roleId,
          });
        }
      }
    }
    return out;
  });

  private roleName(role: Role): string {
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  openMembers(g: Gremium): void {
    this.selectedGremium.set(g);
    this.addPrincipalId.set('');
    this.addRoleId.set('');
    this.memberQuery.set('');
    this.api.listRoles().subscribe((r) => this.memberRoles.set(r));
    this.api.listPrincipals('').subscribe((p) => {
      this.principals.set(p);
      this.candidates.set(p);
    });
  }

  closeMembers(): void {
    this.selectedGremium.set(null);
  }

  onMemberSearch(q: string): void {
    this.memberQuery.set(q);
    this.api.listPrincipals(q).subscribe({
      next: (p) => this.candidates.set(p),
      error: () => this.candidates.set([]),
    });
  }

  addMember(event: Event): void {
    event.preventDefault();
    const g = this.selectedGremium();
    const principalId = this.addPrincipalId();
    const roleId = this.addRoleId();
    if (!g || !principalId || !roleId) return;
    this.api
      .assignRole({ principalId, roleId, gremiumId: g.id, validFrom: null, validUntil: null })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('admin.gremien.memberAdded'));
          this.addPrincipalId.set('');
          this.addRoleId.set('');
          this.refreshPrincipals();
        },
        error: () => this.toast.error(this.i18n.translate('admin.gremien.memberFailed')),
      });
  }

  removeMember(assignmentId: string): void {
    this.api.revokeRole(assignmentId).subscribe({
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

  constructor() {
    this.reload();
  }

  patch<K extends keyof GremiumForm>(key: K, value: GremiumForm[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  startEdit(g: Gremium): void {
    this.editingId.set(g.id);
    this.form.set({
      name: g.name,
      slug: g.slug,
      cdVariant: g.cdVariant,
      defaultLang: g.defaultLang,
    });
  }

  cancelEdit(): void {
    this.editingId.set(null);
    this.form.set(emptyForm());
  }

  submit(event: Event): void {
    event.preventDefault();
    if (!this.canSubmit()) return;
    const f = this.form();
    const cdVariant = f.cdVariant.trim() || 'stupa';
    this.saving.set(true);

    const id = this.editingId();
    if (id) {
      const body: GremiumUpdateBody = {
        name: f.name.trim(),
        slug: f.slug.trim(),
        cdVariant,
        defaultLang: f.defaultLang,
      };
      this.api.updateGremium(id, body).subscribe({
        next: () => this.onSaved('admin.gremien.toast.updated'),
        error: () => this.onSaveError(),
      });
    } else {
      const body: GremiumCreateBody = {
        name: f.name.trim(),
        slug: f.slug.trim(),
        cdVariant,
        defaultLang: f.defaultLang,
      };
      this.api.createGremium(body).subscribe({
        next: () => this.onSaved('admin.gremien.toast.created'),
        error: () => this.onSaveError(),
      });
    }
  }

  private onSaved(key: 'admin.gremien.toast.created' | 'admin.gremien.toast.updated'): void {
    this.saving.set(false);
    this.toast.success(this.i18n.translate(key));
    this.cancelEdit();
    this.reload();
  }

  private onSaveError(): void {
    this.saving.set(false);
    this.toast.error(this.i18n.translate('admin.gremien.toast.failed'));
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.listGremien().subscribe({
      next: (g) => {
        this.gremien.set(g);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }
}
