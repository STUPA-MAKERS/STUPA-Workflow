import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { NotificationPreference } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { CheckboxComponent } from '@shared/ui';

/**
 * Konto → Benachrichtigungen (#4-2): der Nutzer wählt hier ab, welche
 * Mail-Benachrichtigungen er erhalten möchte (Opt-out, Default: alle an).
 * Login-Links (Magic-Link) sind essenziell und tauchen hier nicht auf.
 * Jeder Toggle speichert sofort (Bulk-PUT mit allen Schaltern).
 */
@Component({
  selector: 'app-account-notifications',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, CheckboxComponent],
  template: `
    <section class="notif">
      <header class="notif__head">
        <h1>{{ 'account.notifications.title' | t }}</h1>
        <p class="notif__intro">{{ 'account.notifications.intro' | t }}</p>
      </header>

      @if (error()) {
        <p class="notif__error" role="alert">{{ $any(error()) | t }}</p>
      }

      <section class="card">
        @if (loading()) {
          <p class="notif__muted" aria-live="polite">{{ 'admin.audit.loading' | t }}</p>
        } @else {
          <ul class="notif__list">
            @for (p of prefs(); track p.kind) {
              <li class="notif__item">
                <app-checkbox
                  [ngModel]="p.enabled"
                  (ngModelChange)="toggle(p.kind, $event)"
                  [hint]="kindHint(p.kind)"
                >
                  {{ kindLabel(p.kind) }}
                </app-checkbox>
              </li>
            }
          </ul>
        }
      </section>
    </section>
  `,
  styles: [
    `
      .notif {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
        max-width: 44rem;
      }
      .notif__head h1 {
        margin: 0 0 var(--space-1);
      }
      .notif__intro {
        margin: 0;
        color: var(--color-text-muted);
      }
      .card {
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        padding: var(--space-4) var(--space-5);
        background: var(--color-surface);
      }
      .notif__list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .notif__item + .notif__item {
        border-top: var(--border-width) solid var(--color-border);
        padding-top: var(--space-3);
      }
      .notif__muted {
        color: var(--color-text-muted);
        margin: 0;
      }
      .notif__error {
        color: var(--color-danger);
        margin: 0;
      }
    `,
  ],
})
export class AccountNotificationsComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);

  readonly prefs = signal<NotificationPreference[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  constructor() {
    this.api.listNotificationPreferences().subscribe({
      next: (p) => {
        this.prefs.set(p);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('account.notifications.error');
        this.loading.set(false);
      },
    });
  }

  /** Schalter umlegen → sofort speichern (Server liefert den effektiven Stand). */
  toggle(kind: string, enabled: boolean): void {
    const next = this.prefs().map((p) => (p.kind === kind ? { ...p, enabled } : p));
    this.prefs.set(next);
    this.error.set(null);
    this.api.setNotificationPreferences(next).subscribe({
      next: (saved) => this.prefs.set(saved),
      error: () => this.error.set('account.notifications.saveError'),
    });
  }

  protected kindLabel(kind: string): string {
    return this.lookup(`account.notifications.kind.${kind}`, kind);
  }

  protected kindHint(kind: string): string {
    return this.lookup(`account.notifications.hint.${kind}`, '');
  }

  /** i18n mit Fallback: unbekannte (neue) Kinds zeigen den rohen Key statt zu brechen. */
  private lookup(key: string, fallback: string): string {
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? fallback : label;
  }
}
