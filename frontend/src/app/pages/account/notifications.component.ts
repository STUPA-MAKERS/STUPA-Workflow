import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { NotificationPreference } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { CheckboxComponent } from '@stupa-makers/ui-kit';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

/**
 * Account notification preferences page.
 *
 * The user opts out of mail notifications. All kinds are on by default. The magic-link
 * login mails are essential, so this page does not list them. Each toggle saves
 * immediately and sends all switches in one PUT.
 */
@Component({
  selector: 'app-account-notifications',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SkeletonComponent, FormsModule, TranslatePipe, CheckboxComponent, PageHeaderComponent],
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

  /** Flip one switch and save immediately. The server returns the effective state. */
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

  /** Translate a key. A new kind with no translation shows the fallback, not the key. */
  private lookup(key: string, fallback: string): string {
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? fallback : label;
  }
}
