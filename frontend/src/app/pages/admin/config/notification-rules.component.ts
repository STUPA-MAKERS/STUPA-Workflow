import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  CheckboxComponent,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import { AdminOptionsService } from '../admin-options.service';
import { type NotificationRule } from '../admin.models';

function emptyRule(): NotificationRule {
  return {
    id: '',
    event: 'status_changed',
    recipients: [{ kind: 'applicant' }],
    templateKey: '',
    enabled: true,
  };
}

/**
 * Notification-Regel-UI (T-34, api.md `/admin/notification-rules`). Header mit
 * Anlegen-Button, Liste als geteilte {@link DataTableComponent}, Anlegen/Bearbeiten
 * über einen **Dialog** (#19/#39). Empfänger spiegeln `config_schemas.Recipient`.
 */
@Component({
  selector: 'app-notification-rules',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    SelectComponent,
    BadgeComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
  ],
  template: `
    <section class="cfg">
      <header class="cfg__head">
        <div>
          <h1>{{ 'admin.notif.title' | t }}</h1>
          <p class="cfg__desc">{{ 'admin.notif.desc' | t }}</p>
        </div>
        <app-button size="sm" (click)="openAdd()">{{ 'admin.notif.add' | t }}</app-button>
      </header>

      <app-data-table [columns]="columns()" [rows]="rules()" [emptyText]="'admin.notif.none' | t">
        <ng-template appCell="recipients" let-r>
          <app-badge variant="neutral">{{ $any(r).recipients.length }}</app-badge>
        </ng-template>
        <ng-template appCell="enabled" let-r>
          @if ($any(r).enabled) {
            <span class="cfg__yes" aria-label="✓">✓</span>
          } @else {
            <span class="cfg__no" aria-label="✗">✗</span>
          }
        </ng-template>
        <ng-template appCell="actions" let-r let-i="index">
          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.edit' | t" (click)="openEdit(i)">
            <app-icon name="edit" />
          </app-button>
        </ng-template>
      </app-data-table>
    </section>

    <app-dialog
      [open]="draft() !== null"
      [title]="(editingIndex() === null ? 'admin.notif.add' : 'admin.common.edit') | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="close()"
    >
      @if (draft(); as d) {
        <form class="cfg__form" (submit)="$event.preventDefault(); save()">
          <app-select
            [label]="'admin.notif.event' | t"
            [options]="eventOptions"
            [ngModel]="d.event"
            (ngModelChange)="patch('event', $event)"
            name="event"
          />
          <label class="field">
            <span class="field__label">{{ 'admin.notif.template' | t }}</span>
            <input class="field__control" [ngModel]="d.templateKey" (ngModelChange)="patch('templateKey', $event)" name="template" />
          </label>
          <app-checkbox [ngModel]="d.enabled" (ngModelChange)="patch('enabled', $event)" name="enabled">
            {{ 'admin.notif.enabled' | t }}
          </app-checkbox>

          <fieldset class="cfg__events">
            <legend>{{ 'admin.notif.recipients' | t }}</legend>
            @for (rcpt of d.recipients; track $index; let ri = $index) {
              <div class="cfg__rcpt">
                <app-select
                  [ariaLabel]="'admin.notif.recipients' | t"
                  [options]="kindOptions"
                  [ngModel]="rcpt.kind"
                  (ngModelChange)="setKind(ri, $event)"
                  [name]="'kind-' + ri"
                />
                @if (rcpt.kind === 'role') {
                  <app-select
                    [ariaLabel]="'admin.notif.refRole' | t"
                    [placeholder]="'admin.notif.refRole' | t"
                    [options]="roleOptions()"
                    [ngModel]="rcpt.ref"
                    (ngModelChange)="setRef(ri, $event)"
                    [name]="'ref-' + ri"
                  />
                } @else if (rcpt.kind === 'group') {
                  <app-select
                    [ariaLabel]="'admin.notif.refGroup' | t"
                    [placeholder]="'admin.notif.refGroup' | t"
                    [options]="gremiumOptions()"
                    [ngModel]="rcpt.ref"
                    (ngModelChange)="setRef(ri, $event)"
                    [name]="'ref-' + ri"
                  />
                }
                <app-button variant="danger" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.remove' | t" (click)="removeRcpt(ri)">✕</app-button>
              </div>
            }
            <app-button variant="ghost" size="sm" (click)="addRcpt()">+ {{ 'admin.common.add' | t }}</app-button>
          </fieldset>

          @if (errors().length > 0) {
            <ul class="cfg__errors" role="alert">
              @for (e of errors(); track e) {
                <li>{{ e }}</li>
              }
            </ul>
          }
        </form>
      }
      <div dialog-footer class="cfg__dialog-foot">
        <app-button variant="ghost" (click)="close()">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="errors().length > 0" (click)="save()">{{ 'action.save' | t }}</app-button>
      </div>
    </app-dialog>
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
  protected readonly draft = signal<NotificationRule | null>(null);
  protected readonly editingIndex = signal<number | null>(null);

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'event', label: this.i18n.translate('admin.notif.event') },
    { key: 'templateKey', label: this.i18n.translate('admin.notif.template') },
    { key: 'recipients', label: this.i18n.translate('admin.notif.recipients'), align: 'start', width: '8rem' },
    { key: 'enabled', label: this.i18n.translate('admin.notif.enabled'), align: 'start', width: '6rem' },
    { key: 'actions', label: this.i18n.translate('admin.common.actions'), align: 'end', width: '6rem' },
  ]);

  protected readonly errors = computed(() => {
    const r = this.draft();
    if (!r) return [] as string[];
    const errs: string[] = [];
    if (!r.templateKey.trim()) errs.push('templateKey is required');
    if (r.recipients.length === 0) errs.push('at least one recipient is required');
    for (const rc of r.recipients) {
      if ((rc.kind === 'role' || rc.kind === 'group') && !rc.ref?.trim()) {
        errs.push(`recipient kind '${rc.kind}' requires a ref`);
      }
    }
    return errs;
  });

  constructor() {
    this.api.listNotificationRules().subscribe((r) => this.rules.set(r));
    this.options.roleOptions().subscribe((o) => this.roleOptions.set(o));
    this.options.gremiumOptions().subscribe((o) => this.gremiumOptions.set(o));
  }

  protected openAdd(): void {
    this.editingIndex.set(null);
    this.draft.set(emptyRule());
  }

  protected openEdit(i: number): void {
    this.editingIndex.set(i);
    const src = this.rules()[i];
    this.draft.set({ ...src, recipients: src.recipients.map((rc) => ({ ...rc })) });
  }

  protected close(): void {
    this.draft.set(null);
    this.editingIndex.set(null);
  }

  protected patch<K extends keyof NotificationRule>(key: K, value: NotificationRule[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  protected addRcpt(): void {
    this.draft.update((d) =>
      d ? { ...d, recipients: [...d.recipients, { kind: 'role', ref: '' }] } : d,
    );
  }

  protected removeRcpt(ri: number): void {
    this.draft.update((d) =>
      d ? { ...d, recipients: d.recipients.filter((_, k) => k !== ri) } : d,
    );
  }

  /** `applicant` darf keinen `ref` tragen — beim Wechsel bereinigen. */
  protected setKind(ri: number, kind: 'applicant' | 'role' | 'group'): void {
    this.draft.update((d) => {
      if (!d) return d;
      const recipients = d.recipients.map((rc, k) =>
        k === ri ? (kind === 'applicant' ? { kind } : { kind, ref: rc.ref ?? '' }) : rc,
      );
      return { ...d, recipients };
    });
  }

  protected setRef(ri: number, ref: string): void {
    this.draft.update((d) => {
      if (!d) return d;
      const recipients = d.recipients.map((rc, k) => (k === ri ? { ...rc, ref } : rc));
      return { ...d, recipients };
    });
  }

  protected save(): void {
    const r = this.draft();
    if (!r || this.errors().length > 0) return;
    const idx = this.editingIndex();
    this.api.saveNotificationRule(r).subscribe({
      next: (saved) => {
        this.rules.update((list) =>
          idx === null ? [...list, saved] : list.map((x, i) => (i === idx ? saved : x)),
        );
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.close();
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
