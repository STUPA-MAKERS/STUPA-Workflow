import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, CheckboxComponent, SelectComponent, type SelectOption } from '@shared/ui';
import { ToastService } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import { AdminOptionsService } from '../admin-options.service';
import { type NotificationRule } from '../admin.models';

/**
 * Notification-Regel-UI (T-34, api.md `/admin/notification-rules`). CRUD über die
 * admin-API. Empfänger spiegeln `config_schemas.Recipient`: `applicant` ohne
 * `ref`, `role`/`group` mit Pflicht-`ref`.
 */
@Component({
  selector: 'app-notification-rules',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CheckboxComponent, SelectComponent],
  template: `
    <section class="cfg">
      <header class="cfg__head">
        <h1>{{ 'admin.notif.title' | t }}</h1>
        <app-button variant="secondary" size="sm" (click)="add()">{{ 'admin.notif.add' | t }}</app-button>
      </header>

      <p class="cfg__desc">{{ 'admin.notif.desc' | t }}</p>

      @if (rules().length === 0) {
        <p class="cfg__empty">{{ 'admin.notif.none' | t }}</p>
      }

      @for (rule of rules(); track $index; let i = $index) {
        <article class="cfg__card">
          <div class="cfg__grid">
            <app-select
              class="cfg__lbl"
              [label]="'admin.notif.event' | t"
              [options]="eventOptions"
              [(ngModel)]="rule.event"
              (ngModelChange)="touch()"
            />
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
                <app-select
                  [ariaLabel]="'admin.notif.recipients' | t"
                  [options]="kindOptions"
                  [(ngModel)]="rcpt.kind"
                  (ngModelChange)="onKind(i, ri)"
                />
                @if (rcpt.kind === 'role') {
                  <app-select
                    [ariaLabel]="'admin.notif.refRole' | t"
                    [placeholder]="'admin.notif.refRole' | t"
                    [options]="roleOptions()"
                    [(ngModel)]="rcpt.ref"
                    (ngModelChange)="touch()"
                  />
                } @else if (rcpt.kind === 'group') {
                  <app-select
                    [ariaLabel]="'admin.notif.refGroup' | t"
                    [placeholder]="'admin.notif.refGroup' | t"
                    [options]="gremiumOptions()"
                    [(ngModel)]="rcpt.ref"
                    (ngModelChange)="touch()"
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
  private readonly options = inject(AdminOptionsService);

  protected readonly eventOptions = this.options.eventOptions();
  protected readonly kindOptions = this.options.recipientKindOptions();
  protected readonly roleOptions = signal<SelectOption[]>([]);
  protected readonly gremiumOptions = signal<SelectOption[]>([]);
  protected readonly rules = signal<NotificationRule[]>([]);

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
    this.options.roleOptions().subscribe((o) => this.roleOptions.set(o));
    this.options.gremiumOptions().subscribe((o) => this.gremiumOptions.set(o));
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
