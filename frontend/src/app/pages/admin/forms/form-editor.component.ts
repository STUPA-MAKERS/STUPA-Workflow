import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
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
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import { VersionHistoryComponent } from '../version-history/version-history.component';
import {
  FIELD_TYPES,
  PROMOTE_TARGETS,
  type QuestionGroup,
  blankField,
  blankOption,
  duplicateKeys,
  groupsFromFields,
  groupsToFields,
  normalizeFormField,
  validateFormField,
} from '../form-field.util';

/**
 * Visible order of question types in the "add question" menu. `section` is **not**
 * a selectable type anymore — sections are modeled via group containers (the
 * marker stays only the serialization primitive).
 */
const TYPE_MENU: readonly FieldType[] = FIELD_TYPES.filter((t) => t !== 'section');

/** Stable address of a question: group index + question index within the group. */
interface QPos {
  gi: number;
  qi: number;
}

/**
 * Form editor in **Nextcloud-Forms style**, rebuilt around explicit **question
 * groups**: each group is a titled container (= one wizard step), the group title
 * is the step heading. A group holds the question cards (title/help DE/EN,
 * required, options, ⋯ panel …). Groups can be reordered/added/removed; questions
 * move within a group. On save the groups serialize back into the flat `fields[]`
 * list (a leading `section` marker per group), so backend + apply wizard render one
 * step per group unchanged.
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
    VersionHistoryComponent,
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
  /** Version sidebar — reload after save. */
  protected readonly history = viewChild(VersionHistoryComponent);
  protected readonly title = signal<I18nMap>({ de: '', en: '' });
  protected readonly description = signal<I18nMap>({ de: '', en: '' });
  /** "With budget": allows pot selection on the application (application_type.has_budget). */
  protected readonly hasBudget = signal(false);
  /** Comparison-offers rule: required + minimum count. */
  protected readonly cmpRequired = signal(false);
  protected readonly cmpMinCount = signal(2);
  /** Extra rule fields loaded from the server — preserved on save (not in the UI). */
  private cmpThreshold: string | null = null;
  private cmpAs: 'file' | 'field' | 'both' = 'file';
  /** Editor state: questions grouped into titled containers (= wizard steps). */
  protected readonly groups = signal<QuestionGroup[]>([]);
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  /** Is the current form version active? (usable for new applications) */
  protected readonly active = signal(false);
  /** Current form version — shows which version is being edited. */
  protected readonly formVersion = signal<number | null>(null);
  /** Does a form version exist at all (otherwise nothing to (de)activate)? */
  protected readonly hasVersion = signal(false);
  protected readonly togglingActive = signal(false);
  /** Edit vs. preview (view/edit toggle). */
  protected readonly preview = signal(false);
  /** Which cards show their advanced options (⋯) — key = "gi:qi". */
  protected readonly expanded = signal<Record<string, boolean>>({});
  /** Open "add question" type menu per group (group index or null). */
  protected readonly typeMenuGroup = signal<number | null>(null);
  /** Raw edit strings of the JsonLogic fields ("gi:qi" → {visibleIf, compute}). */
  private readonly rawLogic = signal<Record<string, { visibleIf?: string; compute?: string }>>({});
  /** Currently dragged group (drag-reorder of whole groups). */
  private dragGroup: number | null = null;

  /** Original type state — the type is patched only on change. */
  private originalTitle: I18nMap = { de: '', en: '' };
  private originalHasBudget = false;
  private originalCmpRequired = false;
  private originalCmpMinCount = 2;

  protected readonly fieldTypes = FIELD_TYPES;
  protected readonly typeMenu = TYPE_MENU;
  protected readonly fieldTypeOptions: SelectOption[] = TYPE_MENU.map((t) => ({
    value: t,
    label: this.i18n.translate(`admin.form.type.${t}` as TranslationKey),
  }));
  /** Valid promote targets as a dropdown (only server-evaluated values). */
  protected readonly promoteTargetOptions: SelectOption[] = PROMOTE_TARGETS.map((v) => ({
    value: v,
    label: this.i18n.translate(`admin.form.metric.${v}` as TranslationKey),
  }));

  /** Flat view of the question fields (no markers) — for key/validation checks. */
  private readonly flatQuestions = computed(() => this.groups().flatMap((g) => g.fields));

  protected readonly duplicates = computed(() => duplicateKeys(this.flatQuestions()));
  /** Validation errors per question, indexed by "gi:qi". */
  protected readonly fieldErrors = computed(() => {
    const map: Record<string, string[]> = {};
    this.groups().forEach((g, gi) =>
      g.fields.forEach((f, qi) => {
        map[`${gi}:${qi}`] = validateFormField(f).errors;
      }),
    );
    return map;
  });
  protected readonly formValid = computed(
    () =>
      this.flatQuestions().length > 0 &&
      this.duplicates().length === 0 &&
      Object.values(this.fieldErrors()).every((e) => e.length === 0),
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
          const co = t.comparisonOffers;
          this.cmpRequired.set(co?.required ?? false);
          this.cmpMinCount.set(co?.minCount ?? 2);
          this.cmpThreshold = co?.thresholdAmount ?? null;
          this.cmpAs = co?.as ?? 'file';
          this.originalCmpRequired = this.cmpRequired();
          this.originalCmpMinCount = this.cmpMinCount();
        }
      },
      error: () => undefined,
    });
    this.api.getFormDraft(id).subscribe({
      next: (draft) => {
        // Unpack flat fields into groups (split at `section` markers).
        this.groups.set(
          groupsFromFields(draft.fields.map((f) => ({ ...f, label: { ...f.label } }))),
        );
        const d = draft.description ?? {};
        this.description.set({ de: d['de'] ?? '', en: d['en'] ?? '' });
        this.active.set(draft.active ?? false);
        this.hasVersion.set(!!draft.formVersionId);
        this.formVersion.set(draft.version ?? null);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  /** Reload the editor state after a version restore (sidebar). */
  protected onVersionRestored(): void {
    const id = this.typeId();
    if (id) this.load(id);
  }

  /** Activate/deactivate the form — deactivated blocks new applications. */
  protected toggleActive(): void {
    const id = this.typeId();
    if (!id || this.togglingActive()) return;
    const next = !this.active();
    this.togglingActive.set(true);
    this.api.setFormActive(id, next).subscribe({
      next: (draft) => {
        this.active.set(draft.active ?? false);
        this.hasVersion.set(!!draft.formVersionId);
        this.togglingActive.set(false);
        this.toast.success(
          this.i18n.translate(next ? 'admin.forms.activated' : 'admin.forms.deactivated'),
        );
      },
      error: () => {
        this.togglingActive.set(false);
        this.toast.error(this.i18n.translate('admin.forms.actionFailed'));
      },
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

  // --- group helpers -------------------------------------------------------
  /** Mutate a group in place and poke the signal. */
  private patchGroup(gi: number, fn: (g: QuestionGroup) => QuestionGroup): void {
    this.groups.update((list) => list.map((g, i) => (i === gi ? fn(g) : g)));
  }

  /** Mutate a question in place. */
  private patchQuestion(pos: QPos, fn: (f: FormFieldDef) => FormFieldDef): void {
    this.patchGroup(pos.gi, (g) => ({
      ...g,
      fields: g.fields.map((f, i) => (i === pos.qi ? fn(f) : f)),
    }));
  }

  protected setGroupTitle(gi: number, lang: 'de' | 'en', value: string): void {
    this.patchGroup(gi, (g) => ({ ...g, [lang === 'de' ? 'titleDe' : 'titleEn']: value }));
  }

  protected addGroup(): void {
    this.groups.update((list) => [...list, { titleDe: '', titleEn: '', fields: [] }]);
  }

  protected removeGroup(gi: number): void {
    this.groups.update((list) => list.filter((_, i) => i !== gi));
  }

  protected moveGroup(gi: number, dir: -1 | 1): void {
    this.reorderGroup(gi, gi + dir);
  }

  private reorderGroup(from: number, to: number): void {
    this.groups.update((list) => {
      if (to < 0 || to >= list.length || from === to) return list;
      const next = [...list];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }

  // --- question mutations --------------------------------------------------
  protected addQuestion(gi: number, type: FieldType): void {
    this.patchGroup(gi, (g) => ({ ...g, fields: [...g.fields, blankField(type, '')] }));
    this.typeMenuGroup.set(null);
  }

  protected removeQuestion(pos: QPos): void {
    this.patchGroup(pos.gi, (g) => ({
      ...g,
      fields: g.fields.filter((_, i) => i !== pos.qi),
    }));
  }

  protected duplicateQuestion(pos: QPos): void {
    this.patchGroup(pos.gi, (g) => {
      const copy: FormFieldDef = structuredClone(g.fields[pos.qi]);
      copy.key = copy.key ? `${copy.key}_copy` : '';
      return {
        ...g,
        fields: [...g.fields.slice(0, pos.qi + 1), copy, ...g.fields.slice(pos.qi + 1)],
      };
    });
  }

  /** Move a question within its group; at the edges into the neighboring group. */
  protected moveQuestion(pos: QPos, dir: -1 | 1): void {
    const groups = this.groups();
    const group = groups[pos.gi];
    if (!group) return;
    const target = pos.qi + dir;
    if (target >= 0 && target < group.fields.length) {
      this.patchGroup(pos.gi, (g) => {
        const next = [...g.fields];
        const [moved] = next.splice(pos.qi, 1);
        next.splice(target, 0, moved);
        return { ...g, fields: next };
      });
      return;
    }
    // Hit the edge → hand off to the neighboring group (if any).
    const ngi = pos.gi + dir;
    if (ngi < 0 || ngi >= groups.length) return;
    this.groups.update((list) => {
      const next = list.map((g) => ({ ...g, fields: [...g.fields] }));
      const [moved] = next[pos.gi].fields.splice(pos.qi, 1);
      if (dir === -1) next[ngi].fields.push(moved);
      else next[ngi].fields.unshift(moved);
      return next;
    });
  }

  protected onTypeChange(pos: QPos, type: FieldType): void {
    this.patchQuestion(pos, (f) => this.adaptToType(f, type));
  }

  private adaptToType(field: FormFieldDef, type: FieldType): FormFieldDef {
    const next: FormFieldDef = { ...field, type };
    if ((type === 'select' || type === 'multiselect') && !next.options?.length) {
      next.options = [blankOption()];
    }
    if (type === 'computed' && !next.compute) next.compute = { var: '' };
    // Non-numeric types cannot be promoted into a metric.
    if (type !== 'number' && type !== 'currency') {
      delete next.isPromoted;
      delete next.promoteTarget;
    }
    return next;
  }

  /** PII/metric toggle: on enable, prefill a valid promote target. */
  protected onPromotedToggle(pos: QPos, checked: boolean): void {
    this.patchQuestion(pos, (f) => {
      const next = { ...f, isPromoted: checked };
      if (checked && !next.promoteTarget) next.promoteTarget = PROMOTE_TARGETS[0];
      if (!checked) delete next.promoteTarget;
      return next;
    });
  }

  protected addOption(pos: QPos): void {
    this.patchQuestion(pos, (f) => ({ ...f, options: [...(f.options ?? []), blankOption()] }));
  }

  protected removeOption(pos: QPos, oi: number): void {
    this.patchQuestion(pos, (f) => ({
      ...f,
      options: (f.options ?? []).filter((_, k) => k !== oi),
    }));
  }

  /** Poke mutations so computed signals (validation) recompute. */
  protected touch(): void {
    this.groups.update((list) => [...list]);
  }

  protected toggleExpanded(pos: QPos): void {
    const k = `${pos.gi}:${pos.qi}`;
    this.expanded.update((m) => ({ ...m, [k]: !m[k] }));
  }

  protected isExpanded(pos: QPos): boolean {
    return !!this.expanded()[`${pos.gi}:${pos.qi}`];
  }

  protected errorsFor(gi: number, qi: number): string[] {
    return this.fieldErrors()[`${gi}:${qi}`] ?? [];
  }

  protected isChoice(type: FieldType): boolean {
    return type === 'select' || type === 'multiselect';
  }

  protected isPositions(type: FieldType): boolean {
    return type === 'positions';
  }

  /** Numeric (min/max + promotable). */
  protected isNumeric(type: FieldType): boolean {
    return type === 'number' || type === 'currency';
  }

  /** Text (length/pattern validation applies). */
  protected isText(type: FieldType): boolean {
    return type === 'text' || type === 'textarea';
  }

  // --- drag reorder (groups) -----------------------------------------------
  protected onDragStart(gi: number): void {
    this.dragGroup = gi;
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
  }

  protected onDrop(gi: number): void {
    if (this.dragGroup !== null && this.dragGroup !== gi) this.reorderGroup(this.dragGroup, gi);
    this.dragGroup = null;
  }

  // --- validation field setters --------------------------------------------
  protected setVal(
    pos: QPos,
    key: 'min' | 'max' | 'minLen' | 'maxLen' | 'pattern' | 'minOffers' | 'minPositions',
    value: string,
  ): void {
    const numeric = key !== 'pattern';
    this.patchQuestion(pos, (f) => {
      const validation: Record<string, unknown> = { ...(f.validation ?? {}) };
      if (value === '') delete validation[key];
      else validation[key] = numeric ? Number(value) : value;
      return { ...f, validation: validation as FormFieldDef['validation'] };
    });
  }

  protected onLogicInput(pos: QPos, kind: 'visibleIf' | 'compute', raw: string): void {
    const k = `${pos.gi}:${pos.qi}`;
    this.rawLogic.update((m) => ({ ...m, [k]: { ...m[k], [kind]: raw } }));
    const trimmed = raw.trim();
    this.patchQuestion(pos, (f) => {
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
    });
  }

  protected logicRaw(
    gi: number,
    qi: number,
    kind: 'visibleIf' | 'compute',
    current?: Record<string, unknown>,
  ): string {
    const raw = this.rawLogic()[`${gi}:${qi}`]?.[kind];
    if (raw !== undefined) return raw;
    return current ? JSON.stringify(current) : '';
  }

  // --- save ----------------------------------------------------------------
  private typeChanged(): boolean {
    return (
      this.title()['de'] !== this.originalTitle['de'] ||
      this.title()['en'] !== this.originalTitle['en'] ||
      this.hasBudget() !== this.originalHasBudget ||
      this.cmpRequired() !== this.originalCmpRequired ||
      this.cmpMinCount() !== this.originalCmpMinCount
    );
  }

  protected save(): void {
    const id = this.typeId();
    if (!this.formValid() || !id || this.saving()) {
      this.toast.error(this.i18n.translate('admin.common.invalid'));
      return;
    }
    // Groups → flat fields (marker per group), then normalize as before.
    const flat = groupsToFields(this.groups());
    const normalized = flat.map(normalizeFormField);
    const description: I18nMap = { ...this.description() };
    this.saving.set(true);

    const save$ = this.typeChanged()
      ? this.api
          .updateApplicationType(id, {
            name: { ...this.title() },
            hasBudget: this.hasBudget(),
            comparisonOffers: {
              required: this.cmpRequired(),
              minCount: this.cmpMinCount(),
              thresholdAmount: this.cmpThreshold,
              as: this.cmpAs,
            },
          })
          .pipe(switchMap(() => this.api.createFormVersion(id, normalized, description)))
      : this.api.createFormVersion(id, normalized, description);

    save$.subscribe({
      next: () => {
        this.saving.set(false);
        this.originalTitle = { ...this.title() };
        this.originalHasBudget = this.hasBudget();
        this.originalCmpRequired = this.cmpRequired();
        this.originalCmpMinCount = this.cmpMinCount();
        // Saving creates a new, **active** version.
        this.active.set(true);
        this.hasVersion.set(true);
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.history()?.reload();
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }
}
