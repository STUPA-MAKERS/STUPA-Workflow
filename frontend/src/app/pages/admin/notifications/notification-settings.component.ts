import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, CheckboxComponent } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { AdminApiService } from '../admin-api.service';
import type { NotificationSettings } from '../admin.models';

/**
 * Admin → Benachrichtigungen (#task-reminder, P `admin.notifications`):
 * Plattform-Config der Aufgaben-Erinnerungen — An/Aus, Schwelle in Tagen,
 * Wiederholungs-Intervall (0 = nur einmal je State-Aufenthalt). Der Worker
 * liest diese Werte je Lauf; Speichern wird als CONFIG_CHANGE auditiert.
 */
@Component({
  selector: 'app-notification-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CheckboxComponent],
  templateUrl: './notification-settings.component.html',
  styleUrl: './notification-settings.component.scss',
})
export class NotificationSettingsComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  readonly settings = signal<NotificationSettings | null>(null);
  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly dirty = signal(false);

  constructor() {
    this.api.getNotificationSettings().subscribe({
      next: (s) => {
        this.settings.set(s);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('admin.notifications.error');
        this.loading.set(false);
      },
    });
  }

  patch(change: Partial<NotificationSettings>): void {
    const cur = this.settings();
    if (!cur) return;
    this.settings.set({ ...cur, ...change });
    this.dirty.set(true);
  }

  save(): void {
    const s = this.settings();
    if (!s) return;
    this.saving.set(true);
    this.error.set(null);
    this.api.putNotificationSettings(s).subscribe({
      next: (saved) => {
        this.settings.set(saved);
        this.dirty.set(false);
        this.saving.set(false);
        this.toast.success(this.i18n.translate('admin.notifications.saved'));
      },
      error: () => {
        this.error.set('admin.notifications.saveError');
        this.saving.set(false);
      },
    });
  }
}
