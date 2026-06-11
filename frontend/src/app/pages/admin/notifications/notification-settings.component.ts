import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, CheckboxComponent } from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
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
  template: `
    <section class="ns">
      <header class="ns__head">
        <h1>{{ 'admin.notifications.title' | t }}</h1>
        <p class="ns__intro">{{ 'admin.notifications.intro' | t }}</p>
      </header>

      @if (error()) {
        <p class="ns__error" role="alert">{{ $any(error()) | t }}</p>
      }

      <section class="card">
        <h2>{{ 'admin.notifications.taskReminder' | t }}</h2>
        <p class="ns__muted">{{ 'admin.notifications.taskReminderDesc' | t }}</p>

        @if (loading()) {
          <p class="ns__muted" aria-live="polite">{{ 'common.loading' | t }}</p>
        } @else if (settings(); as s) {
          <div class="ns__form">
            <app-checkbox
              [ngModel]="s.taskReminderEnabled"
              (ngModelChange)="patch({ taskReminderEnabled: $event })"
            >
              {{ 'admin.notifications.enabled' | t }}
            </app-checkbox>

            <label class="field">
              <span class="field__label">{{ 'admin.notifications.afterDays' | t }}</span>
              <input
                class="field__control"
                type="number"
                min="1"
                [disabled]="!s.taskReminderEnabled"
                [ngModel]="s.taskReminderAfterDays"
                (ngModelChange)="patch({ taskReminderAfterDays: $event })"
              />
              <span class="field__hint">{{ 'admin.notifications.afterDaysHint' | t }}</span>
            </label>

            <label class="field">
              <span class="field__label">{{ 'admin.notifications.repeatDays' | t }}</span>
              <input
                class="field__control"
                type="number"
                min="0"
                [disabled]="!s.taskReminderEnabled"
                [ngModel]="s.taskReminderRepeatDays"
                (ngModelChange)="patch({ taskReminderRepeatDays: $event })"
              />
              <span class="field__hint">{{ 'admin.notifications.repeatDaysHint' | t }}</span>
            </label>

            <div class="ns__actions">
              <app-button [disabled]="!dirty() || saving()" (click)="save()">
                {{ 'action.save' | t }}
              </app-button>
            </div>
          </div>
        }
      </section>
    </section>
  `,
  styles: [
    `
      .ns {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
        max-width: 44rem;
      }
      .ns__head h1 {
        margin: 0 0 var(--space-1);
      }
      .ns__intro,
      .ns__muted {
        margin: 0;
        color: var(--color-text-muted);
      }
      .card {
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        padding: var(--space-4) var(--space-5);
        background: var(--color-surface);
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .card h2 {
        margin: 0;
      }
      .ns__form {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
      }
      /* Field-Look des UI-Kits (app-input/.field__control der Config-Seiten). */
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
        max-width: 10rem;
        box-sizing: border-box;
        padding: 0 var(--space-3);
        font: inherit;
        font-size: var(--fs-md);
        line-height: var(--lh-normal);
        color: var(--color-text);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        transition: border-color var(--motion-fast) var(--ease-standard);
      }
      .field__control:hover:not(:disabled) {
        border-color: var(--color-text-muted);
      }
      .field__control:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .field__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .ns__actions {
        display: flex;
        justify-content: flex-end;
      }
      .ns__error {
        color: var(--color-danger);
        margin: 0;
      }
    `,
  ],
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
