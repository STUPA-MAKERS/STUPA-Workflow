import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
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
  InputComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
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
    DialogComponent,
    DataTableComponent,
    CellDirective,
    IconComponent,
    InputComponent,
  ],
  templateUrl: './forms-list.component.html',
  styleUrl: './forms-list.component.scss',
})
export class FormsListComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  /** Antragsarten löschen verlangt die eigene Permission (UX-Gate; Server autoritativ). */
  protected readonly canDelete = computed(() => this.auth.can('admin.types_delete'));
  protected readonly confirmDelete = signal<ApplicationTypeFull | null>(null);
  protected readonly deleting = signal(false);

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
    // Authed /gremien (Dropdown-Quelle) statt admin/gremien — Form-Verwalter (form.configure)
    // braucht kein admin.gremien, um die Gremien-Spalte/Auswahl zu füllen (#5-2).
    this.api.listGremienOptions().subscribe({
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

  protected confirmDeleteName(): string {
    const t = this.confirmDelete();
    return t ? this.name(t) : '';
  }

  protected askDelete(t: ApplicationTypeFull): void {
    this.confirmDelete.set(t);
  }

  protected cancelDelete(): void {
    this.confirmDelete.set(null);
  }

  protected confirmDeleteType(): void {
    const t = this.confirmDelete();
    if (!t || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteApplicationType(t.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(null);
        this.types.update((rows) => rows.filter((r) => r.id !== t.id));
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => {
        this.deleting.set(false);
        // 409 = noch Anträge dieser Art vorhanden; sonst generischer Fehler.
        this.toast.error(this.i18n.translate('admin.forms.deleteFailed'));
      },
    });
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
