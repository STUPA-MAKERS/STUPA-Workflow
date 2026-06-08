import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import { ButtonComponent, CheckboxComponent, ToastService } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import type { Role } from '../admin.models';

/**
 * Rollen-Rechte (#72) — aus dem Benutzer-Screen herausgelöst (eigene Seite, auf
 * Wunsch getrennt). Listet die Rollen und pflegt je Rolle die Berechtigungen
 * (Whitelist aus `/admin/permissions`). Der Server bleibt autoritativ.
 */
@Component({
  selector: 'app-admin-roles',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, CapitalizePipe, ButtonComponent, CheckboxComponent],
  providers: [CapitalizePipe],
  template: `
    <section class="roles">
      <header>
        <h1>{{ 'admin.roles.title' | t }}</h1>
        <p class="roles__sub">{{ 'admin.roles.subtitle' | t }}</p>
      </header>

      @for (r of roles(); track r.id) {
        <article class="roles__card">
          <div class="roles__id">
            <span class="roles__name">{{ roleLabel(r) | capitalize }}</span>
            <span class="roles__key">{{ r.key }}</span>
          </div>

          @if (isLocked(r)) {
            <!-- Admin-Rolle hat IMMER alle Rechte — hier nicht bearbeitbar. -->
            <p class="roles__locked">{{ 'admin.roles.adminLocked' | t }}</p>
            <fieldset class="roles__grid">
              @for (perm of permissions(); track perm) {
                <span class="roles__perm-on">✓ {{ perm }}</span>
              }
            </fieldset>
          } @else {
            <fieldset class="roles__grid">
              <legend class="sr-only">{{ 'admin.roles.permsFor' | t }} {{ roleLabel(r) | capitalize }}</legend>
              @for (perm of permissions(); track perm) {
                <app-checkbox
                  [ngModel]="r.permissions.includes(perm)"
                  (ngModelChange)="togglePerm(r, perm, $event)"
                  [name]="r.id + '-' + perm"
                >{{ perm }}</app-checkbox>
              }
            </fieldset>
            <div class="roles__foot">
              <app-button size="sm" (click)="saveRole(r)">{{ 'action.save' | t }}</app-button>
            </div>
          }
        </article>
      }
    </section>
  `,
  styles: [
    `
      .roles {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .roles__sub {
        color: var(--color-text-muted);
      }
      .roles__card {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
        padding: var(--space-4);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
      }
      .roles__id {
        display: flex;
        align-items: baseline;
        gap: var(--space-3);
      }
      .roles__name {
        font-weight: var(--fw-semibold);
        font-size: var(--fs-md);
      }
      .roles__key {
        color: var(--color-text-muted);
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-sm);
      }
      .roles__grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
        align-items: center;
        gap: var(--space-3);
        margin: 0;
        padding: var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-sm);
      }
      .roles__foot {
        display: flex;
        justify-content: flex-end;
      }
      .roles__locked {
        margin: 0;
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .roles__perm-on {
        font-size: var(--fs-sm);
        color: var(--color-success);
      }
      .sr-only {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
      }
    `,
  ],
})
export class AdminRolesComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly roles = signal<Role[]>([]);
  protected readonly permissions = signal<string[]>([]);

  constructor() {
    this.api.listRoles().subscribe((r) => this.roles.set(r));
    this.api.listPermissions().subscribe((p) => this.permissions.set(p));
  }

  protected roleLabel(role: Role): string {
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  /** Admin-Rolle: immer alle Rechte, hier nicht editierbar (server-autoritativ). */
  protected isLocked(role: Role): boolean {
    return role.key === 'admin';
  }

  protected togglePerm(role: Role, perm: string, on: boolean): void {
    const permissions = on
      ? [...role.permissions, perm]
      : role.permissions.filter((p) => p !== perm);
    this.roles.update((list) => list.map((r) => (r.id === role.id ? { ...r, permissions } : r)));
  }

  protected saveRole(role: Role): void {
    this.api.saveRolePermissions(role.id, role.permissions).subscribe({
      next: (saved) => {
        this.roles.update((list) => list.map((r) => (r.id === saved.id ? saved : r)));
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
