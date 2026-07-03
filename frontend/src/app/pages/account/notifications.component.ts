import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { NotificationPreference } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { CheckboxComponent } from '@stupa-makers/ui-kit';

/**
 * Account notifications: the user opts out of which mail notifications to receive
 * (opt-out, default: all on). Login links (magic-link) are essential and are not
 * listed here. Each toggle saves immediately (bulk PUT with all switches).
 */
@Component({
  selector: 'app-account-notifications',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, CheckboxComponent],
  templateUrl: './notifications.component.html',
  styleUrl: './notifications.component.scss',
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

  /** Flip a switch → save immediately (server returns the effective state). */
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

  /** i18n with fallback: unknown (new) kinds show the raw key instead of breaking. */
  private lookup(key: string, fallback: string): string {
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? fallback : label;
  }
}
