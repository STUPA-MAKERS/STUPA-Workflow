import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, CheckboxComponent } from '@shared/ui';
import { ToastService } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import {
  EVENT_NAMES,
  type NotificationRule,
  type RecipientKind,
} from '../admin.models';

const RECIPIENT_KINDS: readonly RecipientKind[] = ['applicant', 'role', 'group'];

/**
 * Notification-Regel-UI (T-34, api.md `/admin/notification-rules`). CRUD über die
 * admin-API. Empfänger spiegeln `config_schemas.Recipient`: `applicant` ohne
 * `ref`, `role`/`group` mit Pflicht-`ref`.
 */
@Component({
  selector: 'app-notification-rules',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CheckboxComponent],
  template: `
    <section class="cfg">
      <header class="cfg__head">
        <h1>{{ 'admin.notif.title' | t }}</h1>
        <app-button variant="secondary" size="sm" (click)="add()">{{ 'admin.notif.add' | t }}</app-button>
      </header>

      @if (rules().length === 0) {
        <p class="cfg__empty">{{ 'admin.notif.none' | t }}</p>
      }

      @for (rule of rules(); track $index; let i = $index) {
        <article class="cfg__card">
          <div class="cfg__grid">
            <label class="cfg__lbl">{{ 'admin.notif.event' | t }}
              <select [(ngModel)]="rule.event" (ngModelChange)="touch()">
                @for (ev of allEvents; track ev) {
                  <option [value]="ev">{{ ev }}</option>
                }
              </select></label>
            <label class="cfg__lbl">{{ 'admin.notif.template' | t }}
              <input [(ngModel)]="rule.templateKey" (ngModelChange)="touch()" /></label>
            <app-checkbox [(ngModel)]="rule.enabled" (ngModelChange)="touch()">
              {{ 'admin.notif.enabled' | t }}
            </app-checkbox>
          </div>

          <fieldset class="cfg__events">
            <legend>{{ 'admin.notif.recipients' | t }}</legend>
            @for (rcpt of rule.recipients; track $index; let ri = $index) {
              <div class="cfg__rcpt">
                <select [(ngModel)]="rcpt.kind" (ngModelChange)="onKind(i, ri)">
                  @for (k of kinds; track k) {
                    <option [value]="k">{{ rcptLabel(k) }}</option>
                  }
                </select>
                @if (rcpt.kind !== 'applicant') {
                  <input
                    [attr.aria-label]="'admin.common.key' | t"
                    [(ngModel)]="rcpt.ref"
                    (ngModelChange)="touch()"
                    placeholder="ref"
                  />
                }
                <app-button variant="danger" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.remove' | t" (click)="removeRcpt(i, ri)">✕</app-button>
              </div>
            }
            <app-button variant="ghost" size="sm" (click)="addRcpt(i)">+ {{ 'admin.common.add' | t }}</app-button>
          </fieldset>

          @if (errors()[i].length > 0) {
            <ul class="cfg__errors" role="alert">
              @for (e of errors()[i]; track e) {
                <li>{{ e }}</li>
              }
            </ul>
          }

          <div class="cfg__row-foot">
            <app-button variant="ghost" size="sm" (click)="remove(i)">{{ 'admin.common.remove' | t }}</app-button>
            <app-button size="sm" [disabled]="errors()[i].length > 0" (click)="save(i)">{{ 'action.save' | t }}</app-button>
          </div>
        </article>
      }
    </section>
  `,
  styleUrl: './config.shared.scss',
})
export class NotificationRulesComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly allEvents = EVENT_NAMES;
  protected readonly kinds = RECIPIENT_KINDS;
  protected readonly rules = signal<NotificationRule[]>([]);

  protected rcptLabel(kind: RecipientKind): string {
    return this.i18n.translate(`admin.notif.rcpt.${kind}` as TranslationKey);
  }

  protected readonly errors = computed(() =>
    this.rules().map((r) => {
      const errs: string[] = [];
      if (!r.templateKey.trim()) errs.push('templateKey is required');
      if (r.recipients.length === 0) errs.push('at least one recipient is required');
      for (const rc of r.recipients) {
        if ((rc.kind === 'role' || rc.kind === 'group') && !rc.ref?.trim()) {
          errs.push(`recipient kind '${rc.kind}' requires a ref`);
        }
      }
      return errs;
    }),
  );

  constructor() {
    this.api.listNotificationRules().subscribe((r) => this.rules.set(r));
  }

  protected add(): void {
    this.rules.update((list) => [
      ...list,
      { id: '', event: 'status_changed', recipients: [{ kind: 'applicant' }], templateKey: '', enabled: true },
    ]);
  }

  protected remove(i: number): void {
    this.rules.update((list) => list.filter((_, idx) => idx !== i));
  }

  protected addRcpt(i: number): void {
    this.rules.update((list) =>
      list.map((r, idx) =>
        idx === i ? { ...r, recipients: [...r.recipients, { kind: 'role', ref: '' }] } : r,
      ),
    );
  }

  protected removeRcpt(i: number, ri: number): void {
    this.rules.update((list) =>
      list.map((r, idx) =>
        idx === i ? { ...r, recipients: r.recipients.filter((_, k) => k !== ri) } : r,
      ),
    );
  }

  /** `applicant` darf keinen `ref` tragen — beim Wechsel bereinigen. */
  protected onKind(i: number, ri: number): void {
    this.rules.update((list) =>
      list.map((r, idx) => {
        if (idx !== i) return r;
        const recipients = r.recipients.map((rc, k) => {
          if (k !== ri) return rc;
          return rc.kind === 'applicant' ? { kind: rc.kind } : rc;
        });
        return { ...r, recipients };
      }),
    );
  }

  protected touch(): void {
    this.rules.update((list) => [...list]);
  }

  protected save(i: number): void {
    if (this.errors()[i].length > 0) return;
    this.api.saveNotificationRule(this.rules()[i]).subscribe({
      next: (saved) => {
        this.rules.update((list) => list.map((r, idx) => (idx === i ? saved : r)));
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
