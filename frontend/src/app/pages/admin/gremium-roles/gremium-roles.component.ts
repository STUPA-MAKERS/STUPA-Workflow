import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import type { GremiumRole } from '../admin.models';

interface RoleDraft {
  key: string;
  labelDe: string;
  labelEn: string;
}

function emptyDraft(): RoleDraft {
  return { key: '', labelDe: '', labelEn: '' };
}

/**
 * Gremium-Rollen-Katalog (#42): der **eigene** Rollensatz für Gremien, getrennt von
 * den globalen Rollen. CRUD über die Admin-API; Anlegen/Bearbeiten als Dialog (#19).
 * Die konkrete (zeitlich begrenzte) Zuordnung passiert je Gremium auf dessen
 * Mitglieder-Unterseite.
 */
@Component({
  selector: 'app-gremium-roles',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    CapitalizePipe,
    ButtonComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
  ],
  template: `
    <section class="gr">
      <header class="gr__head">
        <div>
          <h1 class="gr__title">{{ 'admin.gremiumRoles.title' | t }}</h1>
          <p class="gr__sub">{{ 'admin.gremiumRoles.subtitle' | t }}</p>
        </div>
        <app-button size="sm" (click)="openAdd()">{{ 'admin.gremiumRoles.add' | t }}</app-button>
      </header>

      <app-data-table [columns]="columns()" [rows]="roles()" [emptyText]="'admin.gremiumRoles.empty' | t">
        <ng-template appCell="name" let-r>{{ label($any(r)) | capitalize }}</ng-template>
        <ng-template appCell="key" let-r><span class="gr__mono">{{ $any(r).key }}</span></ng-template>
        <ng-template appCell="actions" let-r let-i="index">
          <span class="gr__actions">
            <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.edit' | t" (click)="openEdit(i)">
              <app-icon name="edit" />
            </app-button>
            <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.remove' | t" (click)="askDelete($any(r))">
              <app-icon name="delete" />
            </app-button>
          </span>
        </ng-template>
      </app-data-table>
    </section>

    <app-dialog
      [open]="draft() !== null"
      [title]="(editingId() === null ? 'admin.gremiumRoles.add' : 'admin.common.edit') | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="close()"
    >
      @if (draft(); as d) {
        <form class="gr__form" (submit)="$event.preventDefault(); save()">
          <label class="field">
            <span class="field__label">{{ 'admin.common.key' | t }}</span>
            <input class="field__control" [ngModel]="d.key" (ngModelChange)="patch('key', $event)" name="key" [disabled]="editingId() !== null" placeholder="z. B. vorsitz" />
          </label>
          <label class="field">
            <span class="field__label">{{ 'admin.common.labelDe' | t }}</span>
            <input class="field__control" [ngModel]="d.labelDe" (ngModelChange)="patch('labelDe', $event)" name="labelDe" />
          </label>
          <label class="field">
            <span class="field__label">{{ 'admin.common.labelEn' | t }}</span>
            <input class="field__control" [ngModel]="d.labelEn" (ngModelChange)="patch('labelEn', $event)" name="labelEn" />
          </label>
        </form>
      }
      <div dialog-footer class="gr__foot">
        <app-button variant="ghost" (click)="close()">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="!draft()?.key?.trim()" (click)="save()">{{ 'action.save' | t }}</app-button>
      </div>
    </app-dialog>

    <app-dialog
      [open]="confirmDelete() !== null"
      [title]="'admin.gremiumRoles.deleteTitle' | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="confirmDelete.set(null)"
    >
      <p>{{ 'admin.gremiumRoles.deleteConfirm' | t: { name: label(confirmDelete()) } }}</p>
      <div dialog-footer class="gr__foot">
        <app-button variant="ghost" (click)="confirmDelete.set(null)">{{ 'action.cancel' | t }}</app-button>
        <app-button variant="danger" (click)="doDelete()">{{ 'admin.common.remove' | t }}</app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host { display: flex; flex-direction: column; gap: var(--space-5); }
      .gr__head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; }
      .gr__title { margin: 0; }
      .gr__sub { color: var(--color-text-muted); font-size: var(--fs-sm); margin: var(--space-1) 0 0; }
      .gr__mono { font-family: var(--font-mono, monospace); font-size: var(--fs-xs); }
      .gr__actions { display: inline-flex; gap: var(--space-1); justify-content: flex-end; }
      .gr__form { display: flex; flex-direction: column; gap: var(--space-4); }
      .field { display: flex; flex-direction: column; gap: var(--space-2); }
      .field__label { font-size: var(--fs-sm); font-weight: var(--fw-medium); }
      .field__control {
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-surface);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
      }
      .field__control:disabled { opacity: 0.6; cursor: not-allowed; }
      .gr__foot { display: flex; justify-content: flex-end; gap: var(--space-3); }
    `,
  ],
})
export class GremiumRolesComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);

  /** Gremium, dessen Rollen hier verwaltet werden (#62 — Rollen sind pro Gremium). */
  private readonly gremiumId = this.route.snapshot.paramMap.get('id') as Uuid;

  protected readonly roles = signal<GremiumRole[]>([]);
  protected readonly draft = signal<RoleDraft | null>(null);
  protected readonly editingId = signal<string | null>(null);
  protected readonly confirmDelete = signal<GremiumRole | null>(null);

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.gremiumRoles.col.name') },
    { key: 'key', label: this.i18n.translate('admin.gremiumRoles.col.key') },
    { key: 'actions', label: this.i18n.translate('admin.common.actions'), align: 'end', width: '7rem' },
  ]);

  constructor() {
    this.api.listGremiumRoles(this.gremiumId).subscribe((r) => this.roles.set(r));
  }

  protected label(r: GremiumRole | null): string {
    if (!r) return '';
    return r.name[this.i18n.locale()] ?? r.name['de'] ?? r.key;
  }

  protected openAdd(): void {
    this.editingId.set(null);
    this.draft.set(emptyDraft());
  }

  protected openEdit(i: number): void {
    const r = this.roles()[i];
    this.editingId.set(r.id);
    this.draft.set({ key: r.key, labelDe: r.name['de'] ?? '', labelEn: r.name['en'] ?? '' });
  }

  protected close(): void {
    this.draft.set(null);
    this.editingId.set(null);
  }

  protected patch<K extends keyof RoleDraft>(key: K, value: RoleDraft[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  protected save(): void {
    const d = this.draft();
    if (!d || !d.key.trim()) return;
    const name = { de: d.labelDe.trim() || d.key, en: d.labelEn.trim() || d.labelDe.trim() || d.key };
    const id = this.editingId();
    const req = id
      ? this.api.updateGremiumRole(id, { name })
      : this.api.createGremiumRole(this.gremiumId, { key: d.key.trim(), name });
    req.subscribe({
      next: (saved) => {
        this.roles.update((list) =>
          id ? list.map((r) => (r.id === id ? saved : r)) : [...list, saved],
        );
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.close();
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected askDelete(r: GremiumRole): void {
    this.confirmDelete.set(r);
  }

  protected doDelete(): void {
    const r = this.confirmDelete();
    if (!r) return;
    this.api.deleteGremiumRole(r.id).subscribe({
      next: () => {
        this.roles.update((list) => list.filter((x) => x.id !== r.id));
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
