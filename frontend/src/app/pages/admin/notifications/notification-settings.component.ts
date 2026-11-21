import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { InputComponent, SwitchComponent, ToastService } from '@stupa-makers/ui-kit';
import {
  ScreenGroupDirective,
  SettingsScreenComponent,
  type SettingsGroup,
  type SettingsState,
} from '@stupa-makers/ui-kit/screens';
import { I18nService } from '@core/i18n/i18n.service';
import { AdminApiService } from '../admin-api.service';
import type { NotificationSettings } from '../admin.models';

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
    FormsModule,
    TranslatePipe,
    InputComponent,
    SwitchComponent,
    SettingsScreenComponent,
    ScreenGroupDirective,
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

  /** The state of the settings screen (§ui-kit:002244). */
  protected readonly screenState = computed<SettingsState>(() => {
    if (this.loading()) return { state: 'loading', skeleton: { variant: 'lines', count: 4 } };
    if (!this.settings())
      return {
        state: 'error',
        message: this.i18n.translate('admin.notifications.error'),
        retry: () => this.load(),
      };
    return { state: 'ready' };
  });

  /** One group: the task reminder, its switch and its two day fields. */
  protected readonly groups = computed<readonly SettingsGroup[]>(() => [
    {
      key: 'reminder',
      label: this.i18n.translate('admin.notifications.taskReminder'),
      rows: [
        {
          key: 'taskReminderEnabled',
          label: this.i18n.translate('admin.notifications.enabled'),
          control: 'switch',
          value: this.settings()?.taskReminderEnabled ?? false,
        },
      ],
    },
  ]);

  constructor() {
    this.load();
  }

  /** Reads the settings, again after a failed read (§ui-kit:000576). */
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

  /** "Verwerfen": back to the stored values (§ui-kit:000635). */
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
        this.toast.show(this.i18n.translate('admin.notifications.saved'), 'success');
      },
      error: () => {
        this.toast.show(this.i18n.translate('admin.notifications.saveError'), 'error');
        this.saving.set(false);
      },
    });
  }
}
