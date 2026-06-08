import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  ButtonComponent,
  CellDirective,
  CheckboxComponent,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminApiService } from '../admin-api.service';
import {
  CD_VARIANTS,
  type Gremium,
  type GremiumCreateBody,
  type GremiumUpdateBody,
  slugify,
} from '../admin.models';

/** Editier-Formularzustand eines Gremiums (Slug wird automatisch erzeugt). */
interface GremiumForm {
  name: string;
  cdVariant: string;
  defaultLang: string;
  allowVoteDelegation: boolean;
}

function emptyForm(): GremiumForm {
  return { name: '', cdVariant: 'stupa', defaultLang: 'de', allowVoteDelegation: false };
}

/**
 * Gremien-Verwaltung (#18). Tabelle aller Gremien; Anlegen/Bearbeiten über einen
 * **Dialog** (nicht inline). CD-Variante als Dropdown, der Slug wird automatisch
 * aus dem Namen erzeugt, Stimm-Delegation ist eine Gremium-Einstellung (#14).
 * »Mitglieder« führt auf die **Unterseite** je Gremium (`/admin/gremien/:id`).
 */
@Component({
  selector: 'app-admin-gremien',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    SelectComponent,
    DialogComponent,
    DataTableComponent,
    CellDirective,
    IconComponent,
  ],
  template: `
    <header class="grem__head">
      <div>
        <h1 class="grem__title">{{ 'admin.gremien.title' | t }}</h1>
        <p class="grem__subtitle">{{ 'admin.gremien.subtitle' | t }}</p>
      </div>
      <app-button size="sm" (click)="openCreate()">{{ 'admin.gremien.addGremium' | t }}</app-button>
    </header>

    <section class="grem__list" [attr.aria-label]="'admin.gremien.title' | t">
      @if (loading()) {
        <p class="grem__status" aria-live="polite">{{ 'admin.gremien.loading' | t }}</p>
      } @else if (loadError()) {
        <p class="grem__status grem__status--error" role="alert">{{ 'admin.gremien.error' | t }}</p>
      } @else if (!gremien().length) {
        <p class="grem__status">{{ 'admin.gremien.empty' | t }}</p>
      } @else {
        <app-data-table [columns]="columns()" [rows]="gremien()" [rowKey]="rowId">
          <ng-template appCell="slug" let-g><span class="grem__mono">{{ $any(g).slug }}</span></ng-template>
          <ng-template appCell="delegation" let-g>
            @if ($any(g).allowVoteDelegation) {
              <span class="grem__yes" [attr.title]="'admin.gremien.delegation' | t" aria-label="✓">✓</span>
            } @else {
              <span class="grem__no" [attr.title]="'admin.gremien.delegation' | t" aria-label="✗">✗</span>
            }
          </ng-template>
          <ng-template appCell="actions" let-g>
            <span class="grem__th-actions">
              <a class="grem__icon-link" [routerLink]="['/admin/gremien', $any(g).id, 'members']" [attr.aria-label]="'admin.gremien.members' | t" [attr.title]="'admin.gremien.members' | t"><app-icon name="members" /></a>
              <a class="grem__icon-link" [routerLink]="['/admin/gremien', $any(g).id, 'roles']" [attr.aria-label]="'admin.gremiumRoles.manage' | t" [attr.title]="'admin.gremiumRoles.manage' | t"><app-icon name="roles" /></a>
              <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.gremien.editAction' | t" (click)="openEdit($any(g))"><app-icon name="edit" /></app-button>
              <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.gremien.deleteAction' | t" (click)="askDelete($any(g))"><app-icon name="delete" /></app-button>
            </span>
          </ng-template>
        </app-data-table>
      }
    </section>

    <!-- Anlegen/Bearbeiten als Dialog (#18/#19). -->
    <app-dialog
      [open]="dialogOpen()"
      [title]="(editingId() ? 'admin.gremien.edit' : 'admin.gremien.create') | t"
      [closeLabel]="'admin.gremien.cancel' | t"
      (closed)="closeDialog()"
    >
      <form id="grem-form" class="grem__form" (submit)="submit($event)">
        <div class="field">
          <label class="field__label" for="grem-name">{{ 'admin.gremien.name' | t }}</label>
          <input id="grem-name" class="field__control" name="name" [ngModel]="form().name" (ngModelChange)="patch('name', $event)" required />
          <p class="field__hint">{{ 'admin.gremien.slug' | t }}: <span class="grem__mono">{{ slugPreview() }}</span></p>
        </div>
        <app-select
          [label]="'admin.gremien.cdVariant' | t"
          [options]="cdOptions"
          [ngModel]="form().cdVariant"
          (ngModelChange)="patch('cdVariant', $event)"
          name="cdVariant"
        />
        <app-select
          [label]="'admin.gremien.defaultLang' | t"
          [options]="langOptions()"
          [ngModel]="form().defaultLang"
          (ngModelChange)="patch('defaultLang', $event)"
          name="defaultLang"
        />
        <app-checkbox
          [ngModel]="form().allowVoteDelegation"
          (ngModelChange)="patch('allowVoteDelegation', $event)"
          [hint]="'admin.gremien.delegationHint' | t"
          name="delegation"
        >{{ 'admin.gremien.delegation' | t }}</app-checkbox>
      </form>
      <div dialog-footer class="grem__dialog-foot">
        <app-button variant="ghost" (click)="closeDialog()">{{ 'admin.gremien.cancel' | t }}</app-button>
        <app-button [disabled]="!form().name.trim()" [loading]="saving()" (click)="submit($event)">
          {{ (editingId() ? 'admin.gremien.save' : 'admin.gremien.add') | t }}
        </app-button>
      </div>
    </app-dialog>

    <!-- Löschen mit Bestätigung (#41). -->
    <app-dialog
      [open]="confirmDelete() !== null"
      [title]="'admin.gremien.deleteTitle' | t"
      [closeLabel]="'admin.gremien.cancel' | t"
      (closed)="confirmDelete.set(null)"
    >
      <p class="grem__confirm">{{ 'admin.gremien.deleteConfirm' | t: { name: confirmDelete()?.name ?? '' } }}</p>
      <div dialog-footer class="grem__dialog-foot">
        <app-button variant="ghost" (click)="confirmDelete.set(null)">{{ 'admin.gremien.cancel' | t }}</app-button>
        <app-button variant="danger" [loading]="deleting()" (click)="doDelete()">{{ 'admin.gremien.deleteAction' | t }}</app-button>
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
      .grem__head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
      }
      .grem__title {
        margin: 0;
      }
      .grem__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .grem__status {
        color: var(--color-text-muted);
        padding: var(--space-4) 0;
      }
      .grem__status--error {
        color: var(--color-danger);
      }
      .grem__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        overflow: hidden;
      }
      .grem__table th {
        text-align: start;
        padding: var(--space-3) var(--space-4);
        font-size: var(--fs-xs);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--color-text-muted);
        background: var(--color-surface-sunken);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .grem__table td {
        padding: var(--space-3) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
        vertical-align: middle;
      }
      .grem__mono {
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-xs);
      }
      .grem__yes,
      .grem__no {
        font-size: var(--fs-md);
        font-weight: var(--fw-bold);
        line-height: 1;
      }
      .grem__yes {
        color: var(--color-success);
      }
      .grem__no {
        color: var(--color-danger);
      }
      .grem__th-actions {
        text-align: end;
        white-space: nowrap;
      }
      .grem__th-actions {
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        justify-content: flex-end;
      }
      .grem__icon-link {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2rem;
        height: 2rem;
        border-radius: var(--radius-md);
        color: var(--color-text-muted);
      }
      .grem__icon-link:hover {
        color: var(--color-primary);
        background: var(--color-surface-sunken);
      }
      .grem__form {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .field__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
      }
      .field__control {
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-surface);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
      }
      .field__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
        margin: 0;
      }
      .grem__dialog-foot {
        display: flex;
        gap: var(--space-3);
      }
    `,
  ],
})
export class AdminGremienComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly gremien = signal<Gremium[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal(false);
  readonly saving = signal(false);
  readonly dialogOpen = signal(false);
  readonly editingId = signal<Uuid | null>(null);
  readonly form = signal<GremiumForm>(emptyForm());
  readonly confirmDelete = signal<Gremium | null>(null);
  readonly deleting = signal(false);

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.gremien.name') },
    { key: 'slug', label: this.i18n.translate('admin.gremien.slug') },
    { key: 'cdVariant', label: this.i18n.translate('admin.gremien.cdVariant') },
    { key: 'defaultLang', label: this.i18n.translate('admin.gremien.defaultLang') },
    { key: 'delegation', label: this.i18n.translate('admin.gremien.delegationShort'), align: 'start', width: '7rem' },
    { key: 'actions', label: this.i18n.translate('admin.gremien.actions'), align: 'end' },
  ]);
  readonly rowId = (g: unknown): string => (g as Gremium).id;

  readonly cdOptions: SelectOption[] = CD_VARIANTS.map((v) => ({ value: v, label: v }));
  readonly langOptions = computed<SelectOption[]>(() => [
    { value: 'de', label: this.i18n.translate('admin.gremien.langDe') },
    { value: 'en', label: this.i18n.translate('admin.gremien.langEn') },
  ]);

  /** Vorschau des automatisch erzeugten Slugs. */
  readonly slugPreview = computed(() => slugify(this.form().name) || '—');

  constructor() {
    this.reload();
  }

  patch<K extends keyof GremiumForm>(key: K, value: GremiumForm[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  openCreate(): void {
    this.editingId.set(null);
    this.form.set(emptyForm());
    this.dialogOpen.set(true);
  }

  openEdit(g: Gremium): void {
    this.editingId.set(g.id);
    this.form.set({
      name: g.name,
      cdVariant: g.cdVariant,
      defaultLang: g.defaultLang,
      allowVoteDelegation: g.allowVoteDelegation,
    });
    this.dialogOpen.set(true);
  }

  closeDialog(): void {
    this.dialogOpen.set(false);
  }

  submit(event: Event): void {
    event.preventDefault();
    const f = this.form();
    if (!f.name.trim() || this.saving()) return;
    this.saving.set(true);
    const id = this.editingId();
    if (id) {
      const body: GremiumUpdateBody = {
        name: f.name.trim(),
        cdVariant: f.cdVariant,
        defaultLang: f.defaultLang,
        allowVoteDelegation: f.allowVoteDelegation,
      };
      this.api.updateGremium(id, body).subscribe({
        next: () => this.onSaved('admin.gremien.toast.updated'),
        error: () => this.onSaveError(),
      });
    } else {
      const body: GremiumCreateBody = {
        name: f.name.trim(),
        slug: slugify(f.name) || f.name.trim().toLowerCase(),
        cdVariant: f.cdVariant,
        defaultLang: f.defaultLang,
        allowVoteDelegation: f.allowVoteDelegation,
      };
      this.api.createGremium(body).subscribe({
        next: () => this.onSaved('admin.gremien.toast.created'),
        error: () => this.onSaveError(),
      });
    }
  }

  private onSaved(key: 'admin.gremien.toast.created' | 'admin.gremien.toast.updated'): void {
    this.saving.set(false);
    this.dialogOpen.set(false);
    this.toast.success(this.i18n.translate(key));
    this.reload();
  }

  private onSaveError(): void {
    this.saving.set(false);
    this.toast.error(this.i18n.translate('admin.gremien.toast.failed'));
  }

  askDelete(g: Gremium): void {
    this.confirmDelete.set(g);
  }

  doDelete(): void {
    const g = this.confirmDelete();
    if (!g || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteGremium(g.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.gremien.toast.deleted'));
        this.reload();
      },
      error: () => {
        this.deleting.set(false);
        this.toast.error(this.i18n.translate('admin.gremien.toast.failed'));
      },
    });
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.listGremien().subscribe({
      next: (g) => {
        this.gremien.set(g);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }
}
