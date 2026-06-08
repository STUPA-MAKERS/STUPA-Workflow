import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { switchMap } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { FieldType, FormFieldDef, I18nMap, Uuid } from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import {
  ButtonComponent,
  CheckboxComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import {
  FIELD_TYPES,
  PROMOTE_TARGETS,
  blankField,
  blankOption,
  duplicateKeys,
  normalizeFormField,
  validateFormField,
} from '../form-field.util';

/** Sichtbare Reihenfolge der Frage-Typen im »Frage hinzufügen«-Menü. */
const TYPE_MENU: readonly FieldType[] = FIELD_TYPES;

/**
 * Formular-Editor im **Nextcloud-Forms-Stil** (#13). Eine Unterseite je Antragstyp
 * (`/admin/forms/:id`): Titel + mehrsprachige Markdown-Beschreibung, darunter die
 * Fragen als Karten. »+ Frage hinzufügen« öffnet ein Typ-Menü; jede Karte trägt
 * Titel/Beschreibung (DE/EN), Pflicht-Schalter, Auswahloptionen und — eingeklappt
 * unter ⋯ — Schlüssel, PII/Kennzahl und Validierung/JsonLogic. Per Drag oder den
 * Pfeilen umsortierbar. Der »Vorschau«-Modus zeigt das Formular wie beim Ausfüllen.
 * Speichern legt eine neue Form-Version an (Felder serverseitig validiert).
 */
@Component({
  selector: 'app-form-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    SelectComponent,
    IconComponent,
  ],
  templateUrl: './form-editor.component.html',
  styleUrl: './form-editor.component.scss',
})
export class FormEditorComponent {
  private readonly api = inject(AdminApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly typeId = signal<Uuid>('');
  protected readonly title = signal<I18nMap>({ de: '', en: '' });
  protected readonly description = signal<I18nMap>({ de: '', en: '' });
  /** »Mit Budget«: erlaubt die Topf-Auswahl beim Antrag (application_type.has_budget). */
  protected readonly hasBudget = signal(false);
  protected readonly fields = signal<FormFieldDef[]>([]);
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  /** Editieren vs. Vorschau (View/Edit-Toggle, NC-Forms). */
  protected readonly preview = signal(false);
  /** Welche Karten ihre erweiterten Optionen (⋯) zeigen. */
  protected readonly expanded = signal<Record<number, boolean>>({});
  /** Offen: das »Frage hinzufügen«-Typ-Menü. */
  protected readonly typeMenuOpen = signal(false);
  /** Roh-Editierstrings der JsonLogic-Felder (Index → {visibleIf, compute}). */
  private readonly rawLogic = signal<Record<number, { visibleIf?: string; compute?: string }>>({});
  /** Aktuell gezogene Karte (Drag-Reorder). */
  private dragIndex: number | null = null;

  /** Ursprünglicher Typ-Stand — nur bei Änderung wird der Typ gepatcht. */
  private originalTitle: I18nMap = { de: '', en: '' };
  private originalHasBudget = false;

  protected readonly fieldTypes = FIELD_TYPES;
  protected readonly typeMenu = TYPE_MENU;
  protected readonly fieldTypeOptions: SelectOption[] = FIELD_TYPES.map((t) => ({
    value: t,
    label: this.i18n.translate(`admin.form.type.${t}` as TranslationKey),
  }));
  /** Gültige Ziel-Kennzahlen als Dropdown (nur serverseitig ausgewertete Werte). */
  protected readonly promoteTargetOptions: SelectOption[] = PROMOTE_TARGETS.map((v) => ({
    value: v,
    label: this.i18n.translate(`admin.form.metric.${v}` as TranslationKey),
  }));

  protected readonly duplicates = computed(() => duplicateKeys(this.fields()));
  protected readonly fieldErrors = computed(() =>
    this.fields().map((f) => validateFormField(f).errors),
  );
  protected readonly formValid = computed(
    () =>
      this.fields().length > 0 &&
      this.duplicates().length === 0 &&
      this.fieldErrors().every((e) => e.length === 0),
  );

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      const id = params.get('id') ?? '';
      this.typeId.set(id);
      if (id) this.load(id);
    });
  }

  private load(id: Uuid): void {
    this.loading.set(true);
    this.api.listApplicationTypesFull().subscribe({
      next: (types) => {
        const t = types.find((x) => x.id === id);
        if (t) {
          this.title.set({ de: t.name['de'] ?? '', en: t.name['en'] ?? '' });
          this.originalTitle = { ...this.title() };
          this.hasBudget.set(t.hasBudget);
          this.originalHasBudget = t.hasBudget;
        }
      },
      error: () => undefined,
    });
    this.api.getFormDraft(id).subscribe({
      next: (draft) => {
        this.fields.set(draft.fields.map((f) => ({ ...f, label: { ...f.label } })));
        const d = draft.description ?? {};
        this.description.set({ de: d['de'] ?? '', en: d['en'] ?? '' });
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  protected typeLabel(type: FieldType): string {
    return this.i18n.translate(`admin.form.type.${type}` as TranslationKey);
  }

  protected resolved(map: I18nMap | undefined): string {
    return map ? resolveI18n(map, this.i18n.locale()) : '';
  }

  protected setTitle(lang: 'de' | 'en', value: string): void {
    this.title.update((t) => ({ ...t, [lang]: value }));
  }

  protected setDescription(lang: 'de' | 'en', value: string): void {
    this.description.update((d) => ({ ...d, [lang]: value }));
  }

  /** PII-/Kennzahl-Schalter: beim Aktivieren von »In Kennzahl übernehmen« eine
   *  gültige Ziel-Kennzahl vorbelegen (Pflicht laut Validierung). */
  protected onPromotedToggle(i: number, checked: boolean): void {
    this.fields.update((list) =>
      list.map((f, idx) => {
        if (idx !== i) return f;
        const next = { ...f, isPromoted: checked };
        if (checked && !next.promoteTarget) next.promoteTarget = PROMOTE_TARGETS[0];
        if (!checked) delete next.promoteTarget;
        return next;
      }),
    );
  }

  // --- question mutations --------------------------------------------------
  protected addQuestion(type: FieldType): void {
    this.fields.update((list) => [...list, blankField(type, '')]);
    this.typeMenuOpen.set(false);
  }

  protected removeQuestion(i: number): void {
    this.fields.update((list) => list.filter((_, idx) => idx !== i));
  }

  protected duplicateQuestion(i: number): void {
    this.fields.update((list) => {
      const copy: FormFieldDef = structuredClone(list[i]);
      copy.key = copy.key ? `${copy.key}_copy` : '';
      return [...list.slice(0, i + 1), copy, ...list.slice(i + 1)];
    });
  }

  protected move(i: number, dir: -1 | 1): void {
    this.reorder(i, i + dir);
  }

  private reorder(from: number, to: number): void {
    this.fields.update((list) => {
      if (to < 0 || to >= list.length || from === to) return list;
      const next = [...list];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }

  protected onTypeChange(i: number, type: FieldType): void {
    this.fields.update((list) => list.map((f, idx) => (idx === i ? this.adaptToType(f, type) : f)));
  }

  private adaptToType(field: FormFieldDef, type: FieldType): FormFieldDef {
    const next: FormFieldDef = { ...field, type };
    if ((type === 'select' || type === 'multiselect') && !next.options?.length) {
      next.options = [blankOption()];
    }
    if (type === 'computed' && !next.compute) next.compute = { var: '' };
    return next;
  }

  protected addOption(i: number): void {
    this.fields.update((list) =>
      list.map((f, idx) => (idx === i ? { ...f, options: [...(f.options ?? []), blankOption()] } : f)),
    );
  }

  protected removeOption(i: number, oi: number): void {
    this.fields.update((list) =>
      list.map((f, idx) =>
        idx === i ? { ...f, options: (f.options ?? []).filter((_, k) => k !== oi) } : f,
      ),
    );
  }

  /** Mutationen anstoßen, damit Computed-Signale (Validierung) neu rechnen. */
  protected touch(): void {
    this.fields.update((list) => [...list]);
  }

  protected toggleExpanded(i: number): void {
    this.expanded.update((m) => ({ ...m, [i]: !m[i] }));
  }

  protected isExpanded(i: number): boolean {
    return !!this.expanded()[i];
  }

  protected isChoice(type: FieldType): boolean {
    return type === 'select' || type === 'multiselect';
  }

  protected isPositions(type: FieldType): boolean {
    return type === 'positions';
  }

  // --- drag reorder --------------------------------------------------------
  protected onDragStart(i: number): void {
    this.dragIndex = i;
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
  }

  protected onDrop(i: number): void {
    if (this.dragIndex !== null && this.dragIndex !== i) this.reorder(this.dragIndex, i);
    this.dragIndex = null;
  }

  // --- validation field setters (mirror form-builder) ----------------------
  protected setVal(
    i: number,
    key: 'min' | 'max' | 'minLen' | 'maxLen' | 'pattern' | 'minOffers' | 'minPositions',
    value: string,
  ): void {
    const numeric = key !== 'pattern';
    this.fields.update((list) =>
      list.map((f, idx) => {
        if (idx !== i) return f;
        const validation: Record<string, unknown> = { ...(f.validation ?? {}) };
        if (value === '') delete validation[key];
        else validation[key] = numeric ? Number(value) : value;
        return { ...f, validation: validation as FormFieldDef['validation'] };
      }),
    );
  }

  protected onLogicInput(i: number, kind: 'visibleIf' | 'compute', raw: string): void {
    this.rawLogic.update((m) => ({ ...m, [i]: { ...m[i], [kind]: raw } }));
    const trimmed = raw.trim();
    this.fields.update((list) =>
      list.map((f, idx) => {
        if (idx !== i) return f;
        if (trimmed === '') {
          const next = { ...f };
          delete next[kind];
          return next;
        }
        try {
          return { ...f, [kind]: JSON.parse(trimmed) as Record<string, unknown> };
        } catch {
          return f;
        }
      }),
    );
  }

  protected logicRaw(i: number, kind: 'visibleIf' | 'compute', current?: Record<string, unknown>): string {
    const raw = this.rawLogic()[i]?.[kind];
    if (raw !== undefined) return raw;
    return current ? JSON.stringify(current) : '';
  }

  // --- save ----------------------------------------------------------------
  private typeChanged(): boolean {
    return (
      this.title()['de'] !== this.originalTitle['de'] ||
      this.title()['en'] !== this.originalTitle['en'] ||
      this.hasBudget() !== this.originalHasBudget
    );
  }

  protected save(): void {
    const id = this.typeId();
    if (!this.formValid() || !id || this.saving()) {
      this.toast.error(this.i18n.translate('admin.common.invalid'));
      return;
    }
    const normalized = this.fields().map(normalizeFormField);
    const description: I18nMap = { ...this.description() };
    this.saving.set(true);

    const save$ = this.typeChanged()
      ? this.api
          .updateApplicationType(id, { name: { ...this.title() }, hasBudget: this.hasBudget() })
          .pipe(switchMap(() => this.api.createFormVersion(id, normalized, description)))
      : this.api.createFormVersion(id, normalized, description);

    save$.subscribe({
      next: () => {
        this.saving.set(false);
        this.originalTitle = { ...this.title() };
        this.originalHasBudget = this.hasBudget();
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }
}
