import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { I18nMap, Uuid } from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
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
import { type ApplicationTypeFull, type Gremium, slugify } from '../admin.models';

/** Editier-Zustand des Anlegen-Dialogs (Titel DE/EN + Gremium + Budget). */
interface NewForm {
  nameDe: string;
  nameEn: string;
  gremiumId: string;
  hasBudget: boolean;
}

function emptyForm(): NewForm {
  return { nameDe: '', nameEn: '', gremiumId: '', hasBudget: false };
}

/**
 * Formular-/Antragstyp-Übersicht (#13, NC-Forms-Stil). Listet alle Antragstypen
 * als Tabelle; **Anlegen über einen Dialog** (Titel DE/EN, zuständiges Gremium,
 * Budget-Flag). Der Schlüssel wird automatisch aus dem DE-Titel erzeugt. Das
 * Bearbeiten-Icon führt auf die **Unterseite** je Formular (`/admin/forms/:id`),
 * wo die Fragen im Nextcloud-Forms-Stil gepflegt werden.
 */
@Component({
  selector: 'app-forms-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    BadgeComponent,
    CheckboxComponent,
    SelectComponent,
    DialogComponent,
    DataTableComponent,
    CellDirective,
    IconComponent,
  ],
  template: `
    <header class="fl__head">
      <div>
        <h1 class="fl__title">{{ 'admin.forms.listTitle' | t }}</h1>
        <p class="fl__subtitle">{{ 'admin.forms.listSubtitle' | t }}</p>
      </div>
      <app-button size="sm" (click)="openCreate()">{{ 'admin.forms.add' | t }}</app-button>
    </header>

    <section class="fl__list" [attr.aria-label]="'admin.forms.listTitle' | t">
      @if (loading()) {
        <p class="fl__status" aria-live="polite">{{ 'admin.forms.overviewLoading' | t }}</p>
      } @else if (loadError()) {
        <p class="fl__status fl__status--error" role="alert">{{ 'admin.forms.overviewError' | t }}</p>
      } @else {
        <app-data-table [columns]="columns()" [rows]="types()" [rowKey]="rowId" [emptyText]="'admin.forms.overviewEmpty' | t">
          <ng-template appCell="name" let-t>
            <a class="fl__name" [routerLink]="['/admin/forms', $any(t).id]">{{ name($any(t)) }}</a>
          </ng-template>
          <ng-template appCell="gremium" let-t>{{ gremiumName($any(t).gremiumId) }}</ng-template>
          <ng-template appCell="budget" let-t>
            @if ($any(t).hasBudget) {
              <span class="fl__yes" [attr.title]="'admin.forms.hasBudget' | t" aria-label="✓">✓</span>
            } @else {
              <span class="fl__no" [attr.title]="'admin.forms.hasBudget' | t" aria-label="✗">✗</span>
            }
          </ng-template>
          <ng-template appCell="status" let-t>
            <app-badge [variant]="$any(t).activeFormVersionId ? 'success' : 'warning'">
              {{ ($any(t).activeFormVersionId ? 'admin.forms.status.active' : 'admin.forms.status.draft') | t }}
            </app-badge>
          </ng-template>
          <ng-template appCell="actions" let-t>
            <span class="fl__actions">
              <a class="fl__icon-link" [routerLink]="['/admin/forms', $any(t).id]" [attr.aria-label]="'admin.forms.edit' | t" [attr.title]="'admin.forms.edit' | t"><app-icon name="edit" /></a>
            </span>
          </ng-template>
        </app-data-table>
      }
    </section>

    <!-- Anlegen als Dialog (#19). -->
    <app-dialog
      [open]="dialogOpen()"
      [title]="'admin.forms.create' | t"
      [closeLabel]="'admin.common.cancel' | t"
      (closed)="closeDialog()"
    >
      <form id="fl-form" class="fl__form" (submit)="submit($event)">
        <div class="field">
          <label class="field__label" for="fl-name-de">{{ 'admin.forms.nameDe' | t }}</label>
          <input id="fl-name-de" class="field__control" name="nameDe" [ngModel]="form().nameDe" (ngModelChange)="patch('nameDe', $event)" required />
          <p class="field__hint">{{ 'admin.common.key' | t }}: <span class="fl__mono">{{ keyPreview() }}</span></p>
        </div>
        <div class="field">
          <label class="field__label" for="fl-name-en">{{ 'admin.forms.nameEn' | t }}</label>
          <input id="fl-name-en" class="field__control" name="nameEn" [ngModel]="form().nameEn" (ngModelChange)="patch('nameEn', $event)" />
        </div>
        <app-select
          [label]="'admin.forms.gremium' | t"
          [placeholder]="'admin.forms.gremiumNone' | t"
          [options]="gremiumOptions()"
          [ngModel]="form().gremiumId"
          (ngModelChange)="patch('gremiumId', $event)"
          name="gremium"
        />
        <app-checkbox
          [ngModel]="form().hasBudget"
          (ngModelChange)="patch('hasBudget', $event)"
          [hint]="'admin.forms.hasBudgetHint' | t"
          name="hasBudget"
        >{{ 'admin.forms.hasBudget' | t }}</app-checkbox>
      </form>
      <div dialog-footer class="fl__dialog-foot">
        <app-button variant="ghost" (click)="closeDialog()">{{ 'admin.common.cancel' | t }}</app-button>
        <app-button [disabled]="!form().nameDe.trim()" [loading]="saving()" (click)="submit($event)">
          {{ 'admin.forms.add' | t }}
        </app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .fl__head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
      }
      .fl__title {
        margin: 0;
      }
      .fl__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .fl__status {
        color: var(--color-text-muted);
        padding: var(--space-4) 0;
      }
      .fl__status--error {
        color: var(--color-danger);
      }
      .fl__name {
        font-weight: var(--fw-medium);
        color: var(--color-primary);
        text-decoration: none;
      }
      .fl__name:hover {
        text-decoration: underline;
      }
      .fl__yes,
      .fl__no {
        font-size: var(--fs-md);
        font-weight: var(--fw-bold);
        line-height: 1;
      }
      .fl__yes {
        color: var(--color-success);
      }
      .fl__no {
        color: var(--color-danger);
      }
      .fl__actions {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
        justify-content: flex-end;
        width: 100%;
      }
      .fl__icon-link {
        display: inline-flex;
        color: var(--color-text-muted);
      }
      .fl__icon-link:hover {
        color: var(--color-primary);
      }
      .fl__mono {
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-xs);
      }
      .fl__form {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      .field__label {
        font-weight: var(--fw-medium);
        font-size: var(--fs-sm);
      }
      .field__control {
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
        color: inherit;
      }
      .field__hint {
        margin: 0;
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .fl__dialog-foot {
        display: contents;
      }
    `,
  ],
})
export class FormsListComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  protected readonly types = signal<ApplicationTypeFull[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  private readonly gremien = signal<Gremium[]>([]);
  private readonly gremiumMap = computed(() => new Map(this.gremien().map((g) => [g.id, g.name])));

  protected readonly dialogOpen = signal(false);
  protected readonly saving = signal(false);
  protected readonly form = signal<NewForm>(emptyForm());

  constructor() {
    this.reload();
    this.api.listGremien().subscribe({
      next: (g) => this.gremien.set(g),
      error: () => this.gremien.set([]),
    });
  }

  private reload(): void {
    this.loading.set(true);
    this.api.listApplicationTypesFull().subscribe({
      next: (t) => {
        this.types.set(t);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.forms.col.name') },
    { key: 'gremium', label: this.i18n.translate('admin.forms.col.gremium') },
    { key: 'budget', label: this.i18n.translate('admin.forms.col.budget') },
    { key: 'status', label: this.i18n.translate('admin.forms.col.status') },
    { key: 'actions', label: this.i18n.translate('admin.forms.edit'), align: 'end' },
  ]);
  protected readonly rowId = (t: unknown): string => (t as ApplicationTypeFull).id;

  protected readonly gremiumOptions = computed<SelectOption[]>(() =>
    this.gremien().map((g) => ({ value: g.id, label: g.name })),
  );

  protected readonly keyPreview = computed(() => slugify(this.form().nameDe) || '—');

  protected name(t: ApplicationTypeFull): string {
    return resolveI18n(t.name, this.i18n.locale()) || this.i18n.translate('admin.forms.untitled');
  }

  protected gremiumName(id?: Uuid | null): string {
    return (id && this.gremiumMap().get(id)) || '—';
  }

  protected patch<K extends keyof NewForm>(key: K, value: NewForm[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  protected openCreate(): void {
    this.form.set(emptyForm());
    this.dialogOpen.set(true);
  }

  protected closeDialog(): void {
    this.dialogOpen.set(false);
  }

  protected submit(event: Event): void {
    event.preventDefault();
    const f = this.form();
    const nameDe = f.nameDe.trim();
    if (!nameDe || this.saving()) return;
    const name: I18nMap = { de: nameDe, en: f.nameEn.trim() };
    this.saving.set(true);
    this.api
      .createApplicationType({
        key: slugify(nameDe),
        name,
        gremiumId: f.gremiumId || null,
        hasBudget: f.hasBudget,
      })
      .subscribe({
        next: (created) => {
          this.saving.set(false);
          this.dialogOpen.set(false);
          this.toast.success(this.i18n.translate('admin.common.saved'));
          this.router.navigate(['/admin/forms', created.id]);
        },
        error: () => {
          this.saving.set(false);
          this.toast.error(this.i18n.translate('admin.common.saveFailed'));
        },
      });
  }
}
