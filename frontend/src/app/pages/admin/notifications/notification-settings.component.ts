import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  InputComponent,
  SwitchComponent,
  FabComponent,
  ToastService,
  PageHeaderComponent,
  SectionComponent,
  ButtonComponent,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { I18nService } from '@core/i18n/i18n.service';
import { AdminApiService } from '../admin-api.service';
import type { NotificationSettings } from '../admin.models';
import type { LoadState } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';

/**
 * Admin notification settings (permission
 * `admin.notifications`).
 *
 * The page holds the platform config of the task reminders: on or off, the threshold in
 * days (at least 1) and the repeat interval (0 or more). A repeat interval of 0 sends one
 * reminder per stay in a state. The worker reads these values on each run. The server
 * audits a save as CONFIG_CHANGE.
 */
@Component({
  selector: 'app-notification-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    SectionComponent,
    LoadStateComponent,
    FormsModule,
    TranslatePipe,
    FabComponent,
    InputComponent,
    SwitchComponent,
    PageHeaderComponent,
    BreadcrumbsComponent,
  ],
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
  /** The settings as the server has them, for "Verwerfen". */
  private readonly saved = signal<NotificationSettings | null>(null);
  /** The read: loading, then the form, or the error note of a failed read. */
  protected readonly loadState = computed<LoadState>(() =>
    this.loading() ? 'loading' : this.settings() ? 'ok' : 'error',
  );

  /** A whole number of days. The reminder needs at least 1, the repeat at least 0. */
  readonly afterDaysError = computed(() => {
    const s = this.settings();
    return s && !(Number.isInteger(s.taskReminderAfterDays) && s.taskReminderAfterDays >= 1)
      ? this.i18n.translate('admin.notifications.afterDaysError')
      : '';
  });
  readonly repeatDaysError = computed(() => {
    const s = this.settings();
    return s && !(Number.isInteger(s.taskReminderRepeatDays) && s.taskReminderRepeatDays >= 0)
      ? this.i18n.translate('admin.notifications.repeatDaysError')
      : '';
  });
  readonly valid = computed(() => !this.afterDaysError() && !this.repeatDaysError());

  constructor() {
    this.load();
  }

  /** Reads the settings, again after a failed read (§ 000576). */
  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.getNotificationSettings().subscribe({
      next: (s) => {
        this.settings.set(s);
        this.saved.set(s);
        this.dirty.set(false);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('admin.notifications.error');
        this.loading.set(false);
      },
    });
  }

  /** "Verwerfen": back to the stored values (§ 000635). */
  discard(): void {
    this.settings.set(this.saved());
    this.dirty.set(false);
  }

  patch(change: Partial<NotificationSettings>): void {
    const cur = this.settings();
    if (!cur) return;
    this.settings.set({ ...cur, ...change });
    this.dirty.set(true);
  }

  /** The number field gives text; an empty field is not a number. */
  toNumber(value: string | number): number {
    return String(value).trim() === '' ? Number.NaN : Number(value);
  }

  save(): void {
    const s = this.settings();
    if (!s || !this.valid()) return;
    this.saving.set(true);
    this.api.putNotificationSettings(s).subscribe({
      next: (saved) => {
        this.settings.set(saved);
        this.saved.set(saved);
        this.dirty.set(false);
        this.saving.set(false);
        this.toast.success(this.i18n.translate('admin.notifications.saved'));
      },
      error: () => {
        this.toast.error(this.i18n.translate('admin.notifications.saveError'));
        this.saving.set(false);
      },
    });
  }
}
