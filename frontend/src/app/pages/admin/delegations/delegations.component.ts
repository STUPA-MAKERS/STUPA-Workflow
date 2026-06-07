import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { BadgeComponent, ButtonComponent, CheckboxComponent, ToastService } from '@shared/ui';
import { DelegationApiService } from './delegations-api.service';
import type { Delegation, DelegationInput } from './delegations.models';

function emptyDraft(): DelegationInput {
  return {
    principalId: '',
    roleId: '',
    gremiumId: '',
    validFrom: '',
    validUntil: '',
    delegateVoting: false,
  };
}

/**
 * Delegation/Vertretung-UI (T-45, api.md `/delegations`). Mitglied delegiert eine
 * selbst gehaltene Rolle (optional inkl. Stimmrecht) zeitlich begrenzt; Widerruf
 * wirkt sofort. RBAC ist serverseitig autoritativ — diese UI ist nur das Eingabe-/
 * Übersichts-Gate. Client-Validierung: Empfänger + Rolle + Ende(>jetzt) erforderlich.
 */
@Component({
  selector: 'app-delegations',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CheckboxComponent, BadgeComponent],
  template: `
    <section class="cfg">
      <header class="cfg__head">
        <h1>{{ 'admin.deleg.title' | t }}</h1>
      </header>
      <p class="cfg__empty">{{ 'admin.deleg.subtitle' | t }}</p>

      <form class="cfg__card" (ngSubmit)="create()" [attr.aria-label]="'admin.deleg.create' | t">
        <h2>{{ 'admin.deleg.create' | t }}</h2>
        <div class="cfg__grid">
          <label class="cfg__lbl">{{ 'admin.deleg.principal' | t }}
            <input [(ngModel)]="draft().principalId" name="principalId" (ngModelChange)="touch()" />
          </label>
          <label class="cfg__lbl">{{ 'admin.deleg.role' | t }}
            <input [(ngModel)]="draft().roleId" name="roleId" (ngModelChange)="touch()" />
          </label>
          <label class="cfg__lbl">{{ 'admin.deleg.gremium' | t }}
            <input [(ngModel)]="draft().gremiumId" name="gremiumId" (ngModelChange)="touch()" />
          </label>
          <label class="cfg__lbl">{{ 'admin.deleg.validFrom' | t }}
            <input
              type="datetime-local"
              [(ngModel)]="draft().validFrom"
              name="validFrom"
              (ngModelChange)="touch()"
            />
          </label>
          <label class="cfg__lbl">{{ 'admin.deleg.validUntil' | t }}
            <input
              type="datetime-local"
              [(ngModel)]="draft().validUntil"
              name="validUntil"
              (ngModelChange)="touch()"
            />
          </label>
        </div>

        <app-checkbox [(ngModel)]="draft().delegateVoting" name="delegateVoting" (ngModelChange)="touch()">
          {{ 'admin.deleg.voting' | t }}
        </app-checkbox>
        <p class="cfg__empty">{{ 'admin.deleg.votingHint' | t }}</p>

        @if (errors().length > 0) {
          <ul class="cfg__errors" role="alert">
            @for (e of errors(); track e) {
              <li>{{ tr(e) }}</li>
            }
          </ul>
        }

        <div class="cfg__row-foot">
          <app-button type="submit" size="sm" [disabled]="errors().length > 0">
            {{ 'admin.deleg.submit' | t }}
          </app-button>
        </div>
      </form>

      <h2>{{ 'admin.deleg.listTitle' | t }}</h2>
      @if (delegations().length === 0) {
        <p class="cfg__empty">{{ 'admin.deleg.none' | t }}</p>
      }
      @for (d of delegations(); track d.id) {
        <article class="cfg__card">
          <div class="cfg__grid">
            <span class="cfg__lbl">{{ 'admin.deleg.principal' | t }}<strong>{{ d.principalId }}</strong></span>
            <span class="cfg__lbl">{{ 'admin.deleg.role' | t }}<strong>{{ d.roleId }}</strong></span>
            <span class="cfg__lbl">{{ 'admin.deleg.validUntil' | t }}<strong>{{ d.validUntil }}</strong></span>
            <span class="cfg__lbl">{{ 'admin.deleg.voting' | t }}
              <strong>{{ (d.delegateVoting ? 'admin.deleg.yes' : 'admin.deleg.no') | t }}</strong>
            </span>
          </div>
          <div class="cfg__row-foot">
            <app-badge [variant]="d.active ? 'success' : 'neutral'">
              {{ (d.active ? 'admin.deleg.active' : 'admin.deleg.expired') | t }}
            </app-badge>
            <app-button
              variant="ghost"
              size="sm"
              [ariaLabel]="('admin.deleg.revoke' | t) + ' ' + d.principalId"
              (click)="revoke(d.id)"
            >
              {{ 'admin.deleg.revoke' | t }}
            </app-button>
          </div>
        </article>
      }
    </section>
  `,
  styleUrl: '../config/config.shared.scss',
})
export class DelegationsComponent {
  private readonly api = inject(DelegationApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly delegations = signal<Delegation[]>([]);
  protected readonly draft = signal<DelegationInput>(emptyDraft());

  protected readonly errors = computed(() => {
    const d = this.draft();
    const errs: string[] = [];
    if (!d.principalId.trim() || !d.roleId.trim() || !d.validUntil.trim()) {
      errs.push('admin.deleg.errRequired');
    }
    if (d.validUntil.trim() && new Date(d.validUntil).getTime() <= Date.now()) {
      errs.push('admin.deleg.errFuture');
    }
    return errs;
  });

  constructor() {
    this.api.list().subscribe((list) => this.delegations.set(list));
  }

  /** i18n-Key (Validierungsmeldung) übersetzen — Keys sind statisch gepflegt. */
  protected tr(key: string): string {
    return this.i18n.translate(key as TranslationKey);
  }

  /** Signal-Mutation sichtbar machen (ngModel schreibt ins selbe Objekt). */
  protected touch(): void {
    this.draft.update((d) => ({ ...d }));
  }

  protected create(): void {
    if (this.errors().length > 0) return;
    const d = this.draft();
    const payload: DelegationInput = {
      principalId: d.principalId.trim(),
      roleId: d.roleId.trim(),
      gremiumId: d.gremiumId?.trim() ? d.gremiumId.trim() : null,
      validFrom: d.validFrom?.trim() ? d.validFrom.trim() : null,
      validUntil: d.validUntil.trim(),
      delegateVoting: d.delegateVoting,
    };
    this.api.create(payload).subscribe({
      next: (created) => {
        this.delegations.update((list) => [created, ...list]);
        this.draft.set(emptyDraft());
        this.toast.success(this.i18n.translate('admin.deleg.created'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.deleg.createFailed')),
    });
  }

  protected revoke(id: string): void {
    this.api.revoke(id).subscribe({
      next: () => {
        this.delegations.update((list) => list.filter((d) => d.id !== id));
        this.toast.success(this.i18n.translate('admin.deleg.revoked'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.deleg.revokeFailed')),
    });
  }
}
