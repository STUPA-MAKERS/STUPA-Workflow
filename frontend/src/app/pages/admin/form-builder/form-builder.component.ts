import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { FieldType, FormFieldDef } from '@core/api/models';
import { ButtonComponent, CheckboxComponent, SelectComponent, type SelectOption } from '@shared/ui';
import { ToastService } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import {
  FIELD_TYPES,
  blankField,
  blankOption,
  duplicateKeys,
  normalizeFormField,
  serializeFields,
  validateFormField,
} from '../form-field.util';

/**
 * Form-Builder (T-34). Stellt `FormFieldDef[]` visuell zusammen — alle Feldtypen,
 * Validierung, Auswahloptionen, `visibleIf`/`compute` (JsonLogic), i18n-Labels,
 * PII/Promote. Client-Validierung spiegelt das Backend-Schema; Speichern legt
 * eine Form-Version an (api.md `/admin/application-types/{id}/form-versions`).
 *
 * Round-Trip-Garantie: was hier als gültig markiert ist, serialisiert zu validem
 * `FormFieldDef`-JSON (siehe `form-field.util` + Specs).
 */
@Component({
  selector: 'app-form-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CheckboxComponent, SelectComponent],
  templateUrl: './form-builder.component.html',
  styleUrl: './form-builder.component.scss',
})
export class FormBuilderComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly fieldTypes = FIELD_TYPES;
  /** Feldtypen als Dropdown-Optionen (#77) — Wert == Typ-Schlüssel. */
  protected readonly fieldTypeOptions: SelectOption[] = FIELD_TYPES.map((t) => ({ value: t, label: t }));
  protected readonly fields = signal<FormFieldDef[]>([]);
  /** Roh-Editierstrings für JsonLogic-Felder (Index → {visibleIf, compute}). */
  protected readonly rawLogic = signal<Record<number, { visibleIf?: string; compute?: string }>>({});

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

  protected readonly json = computed(() => serializeFields(this.fields()));

  // --- mutations -----------------------------------------------------------
  protected addField(): void {
    this.fields.update((list) => [...list, blankField('text', '')]);
  }

  protected removeField(i: number): void {
    this.fields.update((list) => list.filter((_, idx) => idx !== i));
  }

  protected move(i: number, dir: -1 | 1): void {
    this.fields.update((list) => {
      const next = [...list];
      const j = i + dir;
      if (j < 0 || j >= next.length) return list;
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }

  protected onTypeChange(i: number, type: FieldType): void {
    this.fields.update((list) =>
      list.map((f, idx) => (idx === i ? this.adaptToType(f, type) : f)),
    );
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
      list.map((f, idx) =>
        idx === i ? { ...f, options: [...(f.options ?? []), blankOption()] } : f,
      ),
    );
  }

  protected removeOption(i: number, oi: number): void {
    this.fields.update((list) =>
      list.map((f, idx) =>
        idx === i ? { ...f, options: (f.options ?? []).filter((_, k) => k !== oi) } : f,
      ),
    );
  }

  /** Mutationen anstoßen, damit Computed-Signale (Validierung/JSON) neu rechnen. */
  protected touch(): void {
    this.fields.update((list) => [...list]);
  }

  /** JsonLogic-Rohstring übernehmen: gültiges JSON → ins Feld, sonst Fehler halten. */
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
          return f; // ungültiges JSON → Feld unverändert, Validierung schlägt an
        }
      }),
    );
  }

  protected logicRaw(i: number, kind: 'visibleIf' | 'compute', current?: Record<string, unknown>): string {
    const raw = this.rawLogic()[i]?.[kind];
    if (raw !== undefined) return raw;
    return current ? JSON.stringify(current) : '';
  }

  protected isChoice(type: FieldType): boolean {
    return type === 'select' || type === 'multiselect';
  }

  /** Validierungs-Wert setzen (leer ⇒ entfernen; numerische Keys casten). */
  protected setVal(
    i: number,
    key: 'min' | 'max' | 'minLen' | 'maxLen' | 'pattern',
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

  // --- save ----------------------------------------------------------------
  protected save(): void {
    if (!this.formValid()) {
      this.toast.error(this.i18n.translate('admin.common.invalid'));
      return;
    }
    const normalized = this.fields().map(normalizeFormField);
    // TODO(T-24): echter applicationTypeId aus Routen-/Auswahl-Kontext; im Mock fix.
    this.api.createFormVersion('mock-type', normalized).subscribe({
      next: () => this.toast.success(this.i18n.translate('admin.common.saved')),
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
