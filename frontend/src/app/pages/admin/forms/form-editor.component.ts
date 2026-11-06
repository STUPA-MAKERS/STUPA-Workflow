import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { switchMap } from 'rxjs';
import { I18nService, fallbackChain } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { FieldType, FormFieldDef, I18nMap, Uuid } from '@core/api/models';
import { langFieldLabel, resolveI18n, sameI18n, setI18n } from '@shared/forms/i18n-text';
import {
  ButtonComponent,
  CheckboxComponent,
  EmptyStateComponent,
  IconComponent,
  InputComponent,
  MEDIA,
  mediaQuery,
  MoveButtonsComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  SelectFieldComponent,
  type SelectOption,
  SideSheetComponent,
  StatusTextComponent,
  ToastService,
  FabComponent,
  PageHeaderComponent,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { AdminApiService } from '../admin-api.service';
import { VersionHistoryComponent } from '../version-history/version-history.component';
import {
  FIELD_TYPES,
  PROMOTE_TARGETS,
  type QuestionGroup,
  type QuestionPos,
  blankField,
  blankOption,
  duplicateKeys,
  fundingProblem,
  groupsFromFields,
  groupsToFields,
  moveQuestionTo,
  normalizeFormField,
  validateFormField,
} from '../form-field.util';
import { I18nInputComponent } from '@shared/ui/i18n-input/i18n-input.component';
import { ContentLangSwitchComponent } from '@shared/ui/content-lang-switch/content-lang-switch.component';
import { ContentLangState } from '@shared/ui/content-lang-switch/content-lang.state';
import { withoutKey } from '@shared/util/immutable';

/**
 * Visible order of the question types in the "add question" menu. `section` is **not** a
 * selectable type. Group containers model the sections, and the marker stays the
 * serialization primitive.
 */
const TYPE_MENU: readonly FieldType[] = FIELD_TYPES.filter((t) => t !== 'section');

/** The height of the type menu (nine rows of two types), for the side it opens on. */
const TYPE_MENU_HEIGHT = 9 * 36 + 16;

/** Stable address of a question: group index and question index inside the group. */
type QPos = QuestionPos;

/**
 * Form editor, built
 * around explicit **question groups**.
 *
 * Each group is one wizard step. The group title is the step heading. On save the groups
 * serialize back into the flat `fields[]` list, with a leading `section` marker per
 * group. The backend and the apply wizard therefore still render one step per group.
 *
 * The page has three columns:
 *
 * - The outline: every group ("Abschnitt n · Titel") with its questions (label, required
 *   mark, key and type). A click selects a question. A drag moves a question, also into
 *   another group, or a whole group. "Frage hinzufügen" opens the menu of every question
 *   type (a bottom sheet on a phone). The ⋮ menu of a group moves or deletes it.
 * - The cards of the selected group: the group title, then one card per question with
 *   type, key, required, the labels and help texts in DE and EN, the options of its type
 *   (choice options, cost positions, the expression of a computed field) and the
 *   "Erweiterte Optionen" (PII, metric, validation, visibleIf). The selected question has
 *   an accent outline.
 * - The form settings (title, description, budget, comparison offers) and the versions.
 *
 * Wide (`MEDIA.wide`): a pane page. The page does not scroll; each column scrolls inside
 * itself and fades at an end only where more content is. Narrower, the columns stack.
 *
 * The actions of a card head stop their click, because a click that reaches the card would select
 * the old place again after a move. The menu of the question types sits outside the scrolling
 * columns, so their edges and fades do not cut it.
 */
@Component({
  selector: 'app-form-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [ContentLangState],
  imports: [
    ContentLangSwitchComponent,
    MoveButtonsComponent,
    I18nInputComponent,
    EmptyStateComponent,
    FabComponent,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    SelectFieldComponent,
    IconComponent,
    InputComponent,
    VersionHistoryComponent,
    PageHeaderComponent,
    BreadcrumbsComponent,
    RowMenuComponent,
    SideSheetComponent,
    StatusTextComponent,
    ScrollFadeDirective,
  ],
  host: { '[class.fe-pane]': 'wide()' },
  templateUrl: './form-editor.component.html',
  styleUrl: './form-editor.component.scss',
})
export class FormEditorComponent {
  /** The groups of the outline the first load draws: the name widths of their rows. */
  protected readonly skeletonGroups: readonly (readonly number[])[] = [
    [60, 75, 45, 70, 55],
    [65, 50, 70, 60],
  ];
  /** `n` placeholders for the fields of a skeleton card. */
  protected skeletonFields(n: number): number[] {
    return Array.from({ length: n }, (_, i) => i);
  }

  protected readonly contentLang = inject(ContentLangState);
  private readonly api = inject(AdminApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  protected readonly langFieldLabel = langFieldLabel;
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** Wide viewport: three columns that scroll on their own. */
  protected readonly wide = mediaQuery(MEDIA.wide);
  /** Phone: the header moves its actions into a ⋮ menu. */
  protected readonly phone = mediaQuery(MEDIA.phone);

  protected readonly typeId = signal<Uuid>('');
  /** Version sidebar. Reload it after a save. */
  protected readonly history = viewChild(VersionHistoryComponent);
  protected readonly title = signal<I18nMap>({ de: '', en: '' });
  protected readonly description = signal<I18nMap>({ de: '', en: '' });
  /** "With budget": the application may select a pot (application_type.has_budget). */
  protected readonly hasBudget = signal(false);
  /** Comparison-offers rule: required + minimum count. */
  protected readonly cmpRequired = signal(false);
  protected readonly cmpMinCount = signal(2);
  /** Extra rule fields from the server. A save keeps them. The UI does not show them. */
  private cmpThreshold: string | null = null;
  private cmpAs: 'file' | 'field' | 'both' = 'file';
  /** Editor state: questions grouped into titled containers, one per wizard step. */
  protected readonly groups = signal<readonly QuestionGroup[]>([]);
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  /** Is the current form version active? An active version accepts new applications. */
  protected readonly active = signal(false);
  protected readonly formVersion = signal<number | null>(null);
  /** Does a form version exist? Without one there is nothing to activate or deactivate. */
  protected readonly hasVersion = signal(false);
  protected readonly togglingActive = signal(false);
  protected readonly preview = signal(false);
  /**
   * Which cards show their advanced options (⋯). The key is "gi:qi". A change of the
   * structure (move, drop, delete, duplicate) re-keys it, see `restructure`.
   */
  protected readonly expanded = signal<Record<string, boolean>>({});
  /** Open "add question" type menu per group: the group index, or null for none. */
  protected readonly typeMenuGroup = signal<number | null>(null);
  /** Where the type menu opens: under its button, or above it near the window bottom. */
  protected readonly menuPos = signal<{ left: number; top: number | null; bottom: number | null }>(
    { left: 0, top: 0, bottom: null },
  );
  /**
   * Raw edit strings of the JsonLogic fields: "gi:qi" maps to {visibleIf, compute}. A
   * change of the structure re-keys it, the same as `expanded`.
   */
  private readonly rawLogic = signal<Record<string, { visibleIf?: string; compute?: string }>>({});
  /** The "Frage hinzufügen" button that opened the type menu. Escape gives it the focus. */
  private menuOpener: HTMLElement | null = null;
  /** Closes the type menu on a scroll. Only one is registered at a time. */
  private readonly closeOnScroll = (): void => this.closeTypeMenu(false);
  /** Index of the dragged group during a drag-reorder of whole groups. */
  private dragGroup: number | null = null;
  /** The dragged question during a drag in the outline. */
  private dragQuestion: QPos | null = null;

  /** The group whose cards show in the middle column. */
  protected readonly activeGroup = signal(0);
  /** The selected question: outlined card, highlighted outline row. */
  protected readonly selected = signal<QPos | null>(null);

  /** Index of the shown group, kept inside the list. */
  protected readonly groupIndex = computed(() =>
    Math.max(0, Math.min(this.activeGroup(), this.groups().length - 1)),
  );
  protected readonly currentGroup = computed<QuestionGroup | undefined>(
    () => this.groups()[this.groupIndex()],
  );

  /** The version of the form beside its title ("v7"), or nothing before the first save. */
  protected readonly versionMeta = computed(() => {
    const v = this.formVersion();
    return v === null ? null : this.i18n.translate('admin.forms.versionLabel', { n: v });
  });

  /** The ⋮ menu of the header on a phone: activate or deactivate, and the preview. */
  protected readonly headerMenu = computed<RowMenuSection[]>(() => {
    const toggle: RowMenuItem = {
      id: 'toggleActive',
      label: this.i18n.translate(this.active() ? 'admin.forms.deactivate' : 'admin.forms.activate'),
      icon: 'power',
    };
    const preview: RowMenuItem = {
      id: 'preview',
      label: this.i18n.translate(this.preview() ? 'admin.forms.modeEdit' : 'admin.forms.modeView'),
      icon: this.preview() ? 'edit' : 'eye',
    };
    return [{ items: [...(this.hasVersion() ? [toggle] : []), preview] }];
  });

  /** Original type state. A save patches the type only after a change. */
  private readonly originalType = signal({
    title: { de: '', en: '' } as I18nMap,
    hasBudget: false,
    cmpRequired: false,
    cmpMinCount: 2,
  });
  /** The questions and the description as the server has them (JSON), for `dirty`. */
  private readonly savedForm = signal<string | null>(null);
  /** The questions and the description as the editor has them (JSON). */
  private readonly formSnapshot = computed(() =>
    JSON.stringify({ groups: this.groups(), description: this.description() }),
  );
  /** The type differs from the server: a save patches it before the new form version. */
  private readonly typeChanged = computed(() => {
    const o = this.originalType();
    return (
      !sameI18n(this.title(), o.title) ||
      this.hasBudget() !== o.hasBudget ||
      this.cmpRequired() !== o.cmpRequired ||
      this.cmpMinCount() !== o.cmpMinCount
    );
  });
  /** The editor has changes that are not saved. Only then the page shows "Speichern". */
  protected readonly dirty = computed(
    () =>
      !this.loading() &&
      (this.typeChanged() || (this.savedForm() !== null && this.formSnapshot() !== this.savedForm())),
  );

  protected readonly typeMenu = TYPE_MENU;
  protected readonly fieldTypeOptions: SelectOption[] = TYPE_MENU.map((t) => ({
    value: t,
    label: this.i18n.translate(`admin.form.type.${t}` as TranslationKey),
  }));
  /** Valid promote targets as a dropdown. It lists the server-evaluated values only. */
  protected readonly promoteTargetOptions: SelectOption[] = PROMOTE_TARGETS.map((v) => ({
    value: v,
    label: this.i18n.translate(`admin.form.metric.${v}` as TranslationKey),
  }));

  /** Flat view of the question fields, without markers. The key and validation checks use it. */
  private readonly flatQuestions = computed(() => this.groups().flatMap((g) => g.fields));

  protected readonly duplicates = computed(() => duplicateKeys(this.flatQuestions()));
  /** The form-level problem of the requested funding field, or null. */
  protected readonly fundingIssue = computed(() => fundingProblem(this.flatQuestions()));
  /** Validation errors per question, indexed by "gi:qi". */
  protected readonly fieldErrors = computed(
    (): Readonly<Record<string, readonly string[]>> =>
      Object.fromEntries(
        this.groups().flatMap((g, gi) =>
          g.fields.map((f, qi) => [`${gi}:${qi}`, validateFormField(f).errors]),
        ),
      ),
  );
  protected readonly formValid = computed(
    () =>
      this.flatQuestions().length > 0 &&
      this.duplicates().length === 0 &&
      this.fundingIssue() === null &&
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
          this.title.set({ de: '', en: '', ...t.name });
          this.hasBudget.set(t.hasBudget);
          const co = t.comparisonOffers;
          this.cmpRequired.set(co?.required ?? false);
          this.cmpMinCount.set(co?.minCount ?? 2);
          this.cmpThreshold = co?.thresholdAmount ?? null;
          this.cmpAs = co?.as ?? 'file';
          this.keepTypeAsSaved();
        }
      },
      error: () => undefined,
    });
    this.api.getFormDraft(id).subscribe({
      next: (draft) => {
        this.groups.set(
          groupsFromFields(draft.fields.map((f) => ({ ...f, label: { ...f.label } }))),
        );
        this.activeGroup.set(0);
        this.selected.set(this.groups()[0]?.fields.length ? { gi: 0, qi: 0 } : null);
        const d = draft.description ?? {};
        this.description.set({ de: '', en: '', ...d });
        this.active.set(draft.active ?? false);
        this.hasVersion.set(!!draft.formVersionId);
        this.formVersion.set(draft.version ?? null);
        this.savedForm.set(this.formSnapshot());
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

  /** Activate or deactivate the form. A deactivated form blocks new applications. */
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
    return map ? resolveI18n(map, this.i18n.uiLocale()) : '';
  }

  /**
   * The help text of an info field in the preview, or '' when it has none or when it only
   * repeats the label. The wizard shows such an info text once: no bold label over the
   * same text (the preview follows the same rule).
   */
  protected infoHelp(field: FormFieldDef): string {
    const help = this.resolved(field.help).trim();
    return help && help !== this.resolved(field.label).trim() ? help : '';
  }

  /** The description that a reader of the content language gets while its field is empty. */
  protected readonly descFallback = computed(() => {
    const map = this.description();
    return fallbackChain(this.contentLang.lang()).slice(1).map((code) => map[code]).find(Boolean) ?? '';
  });

  protected setDescription(lang: string, value: string): void {
    this.description.update((d) => setI18n(d, lang, value));
  }

  /** Replace one group and poke the signal. */
  private patchGroup(gi: number, fn: (g: QuestionGroup) => QuestionGroup): void {
    this.groups.update((list) => list.map((g, i) => (i === gi ? fn(g) : g)));
  }

  private patchQuestion(pos: QPos, fn: (f: FormFieldDef) => FormFieldDef): void {
    this.patchGroup(pos.gi, (g) => ({
      ...g,
      fields: g.fields.map((f, i) => (i === pos.qi ? fn(f) : f)),
    }));
  }

  protected setGroupTitle(gi: number, title: I18nMap): void {
    this.patchGroup(gi, (g) => ({ ...g, title }));
  }

  protected addGroup(): void {
    this.groups.update((list) => [...list, { title: { de: '', en: '' }, fields: [] }]);
    this.selectGroup(this.groups().length - 1);
  }

  protected removeGroup(gi: number): void {
    this.restructure(() => this.groups.update((list) => list.filter((_, i) => i !== gi)));
    const sel = this.selected();
    if (sel?.gi === gi) this.selected.set(null);
    else if (sel && sel.gi > gi) this.selected.set({ gi: sel.gi - 1, qi: sel.qi });
    const active = this.activeGroup();
    if (active > gi || active >= this.groups().length) this.activeGroup.set(Math.max(0, active - 1));
  }

  protected moveGroup(gi: number, dir: -1 | 1): void {
    this.reorderGroup(gi, gi + dir);
  }

  private reorderGroup(from: number, to: number): void {
    const len = this.groups().length;
    if (to < 0 || to >= len || from === to) return;
    this.restructure(() =>
      this.groups.update((list) => movedTo(list, from, to)),
    );
    const place = (i: number): number => {
      if (i === from) return to;
      if (from < to && i > from && i <= to) return i - 1;
      if (from > to && i >= to && i < from) return i + 1;
      return i;
    };
    this.activeGroup.set(place(this.activeGroup()));
    const sel = this.selected();
    if (sel) this.selected.set({ gi: place(sel.gi), qi: sel.qi });
  }

  /** Show a group in the middle column, without a selected question. */
  protected selectGroup(gi: number): void {
    this.activeGroup.set(gi);
    this.selected.set(null);
  }

  /**
   * Select a question: show its group and outline its card. `scroll` brings the card into
   * view (a click in the outline); a click into the card itself does not move the page.
   */
  protected selectQuestion(pos: QPos, scroll = true): void {
    this.activeGroup.set(pos.gi);
    this.selected.set(pos);
    if (scroll) this.scrollToCard(pos);
  }

  /**
   * Open or close the type menu of a group at its button. The menu opens below the
   * button, or above it when the space below is too small for it.
   *
   * On a phone the menu is a bottom sheet, so a scroll inside the sheet must not close it.
   * Elsewhere a scroll closes the menu before it can drift away from its button.
   */
  protected toggleTypeMenu(gi: number, event: Event): void {
    if (this.typeMenuGroup() === gi) {
      this.closeTypeMenu(false);
      return;
    }
    const button = (event.currentTarget as HTMLElement | null) ?? null;
    this.menuOpener = button;
    const rect = button?.getBoundingClientRect();
    if (rect) {
      const below = window.innerHeight - rect.bottom;
      this.menuPos.set(
        below < TYPE_MENU_HEIGHT
          ? { left: rect.left, top: null, bottom: window.innerHeight - rect.top + 4 }
          : { left: rect.left, top: rect.bottom + 4, bottom: null },
      );
    }
    this.typeMenuGroup.set(gi);
    if (this.phone()) return;
    window.removeEventListener('scroll', this.closeOnScroll, { capture: true });
    window.addEventListener('scroll', this.closeOnScroll, { capture: true, once: true });
    setTimeout(() => this.menuItems()[0]?.focus({ preventScroll: true }));
  }

  /** Close the type menu. With `refocus`, the button that opened it gets the focus again. */
  protected closeTypeMenu(refocus: boolean): void {
    if (this.typeMenuGroup() === null) return;
    this.typeMenuGroup.set(null);
    window.removeEventListener('scroll', this.closeOnScroll, { capture: true });
    if (refocus) {
      const opener = this.menuOpener;
      (opener?.querySelector<HTMLElement>('button') ?? opener)?.focus({ preventScroll: true });
    }
  }

  /** The type buttons of the open menu (wide and tablet only). */
  private menuItems(): HTMLElement[] {
    return Array.from(
      this.host.nativeElement.querySelectorAll<HTMLElement>('.fe__menu .fe__menu-item'),
    );
  }

  /**
   * Keyboard in the type menu: the arrow keys, Home and End move between the types. Tab
   * closes the menu and gives the focus back to its button.
   */
  protected onMenuKeydown(event: KeyboardEvent): void {
    const items = this.menuItems();
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === 'Tab') {
      event.preventDefault();
      this.closeTypeMenu(true);
      return;
    }
    const next = menuTarget(event.key, at, items.length);
    if (next === null) return;
    event.preventDefault();
    items[next]?.focus({ preventScroll: true });
  }

  /** Escape closes the open type menu, wherever the focus is, and focuses its button. */
  @HostListener('document:keydown.escape')
  protected onDocumentEscape(): void {
    if (this.typeMenuGroup() === null || this.phone()) return;
    this.closeTypeMenu(true);
  }

  /** A press outside the type menu and its buttons closes the menu. */
  @HostListener('document:pointerdown', ['$event'])
  protected onDocumentPointerDown(event: PointerEvent): void {
    if (this.typeMenuGroup() === null || this.phone()) return;
    const target = event.target as Element | null;
    if (target?.closest('.fe__menu, .fe__addBtn')) return;
    this.closeTypeMenu(false);
  }

  /** A click or the focus in a card selects its question, without a scroll. */
  protected focusCard(pos: QPos): void {
    if (!this.isSelected(pos.gi, pos.qi)) this.selectQuestion(pos, false);
  }

  protected isSelected(gi: number, qi: number): boolean {
    const sel = this.selected();
    return !!sel && sel.gi === gi && sel.qi === qi;
  }

  /** Scroll the card of a question into view once it is rendered. */
  private scrollToCard(pos: QPos): void {
    setTimeout(() => {
      const card = this.host.nativeElement.querySelector<HTMLElement>(
        `[data-q="${pos.gi}:${pos.qi}"]`,
      );
      card?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
    });
  }

  /** An action of the ⋮ menu of a group in the outline. */
  protected onGroupMenu(gi: number, item: RowMenuItem): void {
    if (item.id === 'up') this.moveGroup(gi, -1);
    else if (item.id === 'down') this.moveGroup(gi, 1);
    else if (item.id === 'delete') this.removeGroup(gi);
  }

  /** The ⋮ menu of a group: move it up or down (not past an edge) and delete it. */
  protected groupMenu(gi: number): RowMenuSection[] {
    const last = this.groups().length - 1;
    const up: RowMenuItem = {
      id: 'up',
      label: this.i18n.translate('admin.form.moveGroupUp'),
      icon: 'up',
    };
    const down: RowMenuItem = {
      id: 'down',
      label: this.i18n.translate('admin.form.moveGroupDown'),
      icon: 'down',
    };
    const move = [...(gi > 0 ? [up] : []), ...(gi < last ? [down] : [])];
    return [
      { items: move },
      {
        items: [
          { id: 'delete', label: this.i18n.translate('admin.form.deleteGroup'), icon: 'trash', danger: true },
        ],
      },
    ];
  }

  /** An action of the ⋮ menu of the header (phone). */
  protected onHeaderMenu(item: RowMenuItem): void {
    switch (item.id) {
      case 'toggleActive':
        return this.toggleActive();
      case 'preview':
        return this.preview.set(!this.preview());
      default:
        return;
    }
  }

  /** The heading of a group in the outline and on its card: "Abschnitt 2 · Kosten". */
  protected groupHeading(group: QuestionGroup, gi: number): string {
    const step = this.i18n.translate('admin.form.groupStep', { n: gi + 1 });
    const title = this.resolved(group.title);
    return title ? `${step} · ${title}` : step;
  }

  protected addQuestion(gi: number, type: FieldType): void {
    this.patchGroup(gi, (g) => ({ ...g, fields: [...g.fields, blankField(type, '')] }));
    this.closeTypeMenu(false);
    const qi = (this.groups()[gi]?.fields.length ?? 1) - 1;
    this.selectQuestion({ gi, qi });
  }

  protected removeQuestion(pos: QPos): void {
    this.restructure(() =>
      this.patchGroup(pos.gi, (g) => ({
        ...g,
        fields: g.fields.filter((_, i) => i !== pos.qi),
      })),
    );
    const sel = this.selected();
    if (sel?.gi !== pos.gi) return;
    if (sel.qi === pos.qi) this.selected.set(null);
    else if (sel.qi > pos.qi) this.selected.set({ gi: sel.gi, qi: sel.qi - 1 });
  }

  protected duplicateQuestion(pos: QPos): void {
    this.restructure(() =>
      this.patchGroup(pos.gi, (g) => {
        const clone: FormFieldDef = structuredClone(g.fields[pos.qi]);
        const copy: FormFieldDef = { ...clone, key: clone.key ? `${clone.key}_copy` : '' };
        return {
          ...g,
          fields: [...g.fields.slice(0, pos.qi + 1), copy, ...g.fields.slice(pos.qi + 1)],
        };
      }),
    );
    this.selectQuestion({ gi: pos.gi, qi: pos.qi + 1 });
  }

  /** Move a question inside its group. At an edge it moves into the neighboring group. */
  protected moveQuestion(pos: QPos, dir: -1 | 1): void {
    const groups = this.groups();
    const group = groups[pos.gi];
    if (!group) return;
    const target = pos.qi + dir;
    if (target >= 0 && target < group.fields.length) {
      this.restructure(() =>
        this.patchGroup(pos.gi, (g) => ({ ...g, fields: movedTo(g.fields, pos.qi, target) })),
      );
      this.follow(pos, { gi: pos.gi, qi: target });
      return;
    }
    const ngi = pos.gi + dir;
    if (ngi < 0 || ngi >= groups.length) return;
    this.restructure(() =>
      this.groups.update((list) => {
        const moved = list[pos.gi].fields[pos.qi];
        return list.map((g, gi) => {
          if (gi === pos.gi) return { ...g, fields: g.fields.filter((_, qi) => qi !== pos.qi) };
          if (gi !== ngi) return { ...g, fields: [...g.fields] };
          return { ...g, fields: dir === -1 ? [...g.fields, moved] : [moved, ...g.fields] };
        });
      }),
    );
    this.follow(pos, { gi: ngi, qi: dir === -1 ? groups[ngi].fields.length : 0 });
  }

  /**
   * Run a change of the structure (a move, drop, delete or duplicate of questions or
   * groups) and re-key the per-question editor state ("gi:qi") to the new places.
   *
   * The change keeps the question objects, so each old key goes to the place where its
   * object is now. The state of a deleted question goes away. A copy starts without state.
   */
  private restructure(change: () => void): void {
    const before = this.groups();
    change();
    const now = new Map(
      this.groups().flatMap((g, gi) => g.fields.map((f, qi) => [f, `${gi}:${qi}`] as const)),
    );
    const placeOf = (key: string): string | undefined => {
      const [gi, qi] = key.split(':').map(Number);
      const field = before[gi]?.fields[qi];
      return field ? now.get(field) : undefined;
    };
    const rekey = <T>(map: Record<string, T>): Record<string, T> =>
      Object.fromEntries(
        Object.entries(map).flatMap(([key, value]) => {
          const to = placeOf(key);
          return to !== undefined ? [[to, value] as const] : [];
        }),
      );
    this.expanded.update(rekey);
    this.rawLogic.update(rekey);
  }

  /** The selection follows a moved question to its new place. */
  private follow(from: QPos, to: QPos): void {
    if (this.isSelected(from.gi, from.qi)) this.selectQuestion(to);
  }

  protected onTypeChange(pos: QPos, type: FieldType): void {
    this.patchQuestion(pos, (f) => this.adaptToType(f, type));
  }

  private adaptToType(field: FormFieldDef, type: FieldType): FormFieldDef {
    const needsOption = (type === 'select' || type === 'multiselect') && !field.options?.length;
    const next: FormFieldDef = {
      ...field,
      type,
      ...(needsOption ? { options: [blankOption()] } : {}),
      ...(type === 'computed' && !field.compute ? { compute: { var: '' } } : {}),
    };
    if (type === 'number' || type === 'currency') return next;
    return withoutKey(withoutKey(next, 'isPromoted'), 'promoteTarget');
  }

  /** Metric toggle: prefill a valid promote target when the user turns it on. */
  protected onPromotedToggle(pos: QPos, checked: boolean): void {
    this.patchQuestion(pos, (f) => {
      const next = { ...f, isPromoted: checked };
      if (!checked) return withoutKey(next, 'promoteTarget');
      return next.promoteTarget ? next : { ...next, promoteTarget: PROMOTE_TARGETS[0] };
    });
  }

  protected addOption(pos: QPos): void {
    this.patchQuestion(pos, (f) => ({ ...f, options: [...(f.options ?? []), blankOption()] }));
  }

  /** Set fields of one question; the template binds its edits here instead of writing in place. */
  protected setQuestion(pos: QPos, patch: Partial<FormFieldDef>): void {
    this.patchQuestion(pos, (f) => ({ ...f, ...patch }));
  }

  /** Set the label of one option of a question. */
  protected setOptionLabel(pos: QPos, oi: number, label: I18nMap): void {
    this.patchQuestion(pos, (f) => ({
      ...f,
      options: (f.options ?? []).map((o, k) => (k === oi ? { ...o, label } : o)),
    }));
  }

  protected removeOption(pos: QPos, oi: number): void {
    this.patchQuestion(pos, (f) => ({
      ...f,
      options: (f.options ?? []).filter((_, k) => k !== oi),
    }));
  }

  /** Poke the signal so the computed values, such as the validation, recompute. */
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

  protected errorsFor(gi: number, qi: number): readonly string[] {
    return this.fieldErrors()[`${gi}:${qi}`] ?? [];
  }

  protected isChoice(type: FieldType): boolean {
    return type === 'select' || type === 'multiselect';
  }

  protected isPositions(type: FieldType): boolean {
    return type === 'positions';
  }

  /** Numeric types: they accept min and max, and they can be promoted. */
  protected isNumeric(type: FieldType): boolean {
    return type === 'number' || type === 'currency';
  }

  /** Text types: the length and pattern validation applies. */
  protected isText(type: FieldType): boolean {
    return type === 'text' || type === 'textarea';
  }

  protected onDragStart(gi: number): void {
    this.dragGroup = gi;
    this.dragQuestion = null;
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
  }

  /**
   * A drop on a group: a dragged group takes its place; a dragged question goes to the
   * end of the group.
   */
  protected onDrop(gi: number): void {
    const q = this.dragQuestion;
    if (q) {
      this.dropQuestion(q, { gi, qi: this.groups()[gi]?.fields.length ?? 0 });
    } else if (this.dragGroup !== null && this.dragGroup !== gi) {
      this.reorderGroup(this.dragGroup, gi);
    }
    this.dragGroup = null;
    this.dragQuestion = null;
  }

  /**
   * Start the drag of a question in the outline.
   *
   * The group around the row must not start a group drag.
   */
  protected onQuestionDragStart(event: DragEvent, pos: QPos): void {
    event.stopPropagation();
    event.dataTransfer?.setData('text/plain', `${pos.gi}:${pos.qi}`);
    this.dragQuestion = pos;
    this.dragGroup = null;
  }

  /** A drop on a question row: the dragged question takes the place of that row. */
  protected onQuestionDrop(event: DragEvent, pos: QPos): void {
    const q = this.dragQuestion;
    if (!q) return;
    event.preventDefault();
    event.stopPropagation();
    this.dropQuestion(q, pos);
    this.dragQuestion = null;
  }

  private dropQuestion(from: QPos, to: QPos): void {
    if (from.gi === to.gi && from.qi === to.qi) return;
    const sel = this.selected();
    const selField = sel ? this.groups()[sel.gi]?.fields[sel.qi] : undefined;
    const moved = moveQuestionTo(this.groups(), from, to);
    if (!moved) return;
    this.restructure(() => this.groups.set(moved.groups));
    if (!selField) return;
    moved.groups.forEach((g, gi) => {
      const qi = g.fields.indexOf(selField);
      if (qi >= 0) this.selectQuestion({ gi, qi }, gi === moved.pos.gi && qi === moved.pos.qi);
    });
  }

  protected setVal(
    pos: QPos,
    key: 'min' | 'max' | 'minLen' | 'maxLen' | 'pattern' | 'minOffers' | 'minPositions',
    value: string,
  ): void {
    const numeric = key !== 'pattern';
    this.patchQuestion(pos, (f) => {
      const current = f.validation ?? {};
      const validation =
        value === ''
          ? withoutKey(current, key)
          : { ...current, [key]: numeric ? Number(value) : value };
      return { ...f, validation: validation as FormFieldDef['validation'] };
    });
  }

  /** Opt-out of comparison offers. Allowed is the default, so only `false` is stored. */
  protected setAllowNoOffers(pos: QPos, allowed: boolean): void {
    this.patchQuestion(pos, (f) => {
      const current = f.validation ?? {};
      const validation = allowed
        ? withoutKey(current, 'allowNoOffers')
        : { ...current, allowNoOffers: false };
      return { ...f, validation: validation as FormFieldDef['validation'] };
    });
  }

  protected onLogicInput(pos: QPos, kind: 'visibleIf' | 'compute', raw: string): void {
    const k = `${pos.gi}:${pos.qi}`;
    this.rawLogic.update((m) => ({ ...m, [k]: { ...m[k], [kind]: raw } }));
    const trimmed = raw.trim();
    this.patchQuestion(pos, (f) => {
      if (trimmed === '') return withoutKey(f, kind);
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

  /** The type fields of the editor are now the state of the server. */
  private keepTypeAsSaved(): void {
    this.originalType.set({
      title: { ...this.title() },
      hasBudget: this.hasBudget(),
      cmpRequired: this.cmpRequired(),
      cmpMinCount: this.cmpMinCount(),
    });
  }

  protected save(): void {
    const id = this.typeId();
    if (!this.formValid() || !id || this.saving()) {
      this.toast.error(this.i18n.translate('admin.common.invalid'));
      return;
    }
    const flat = groupsToFields(this.groups());
    const normalized = flat.map(normalizeFormField);
    const description: I18nMap = { ...this.description() };
    const snapshot = this.formSnapshot();
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
        this.keepTypeAsSaved();
        this.savedForm.set(snapshot);
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

/** The index the arrow, Home or End key moves the type menu focus to, or null for another key. */
function menuTarget(key: string, at: number, length: number): number | null {
  switch (key) {
    case 'ArrowDown':
    case 'ArrowRight':
      return at < 0 ? 0 : (at + 1) % length;
    case 'ArrowUp':
    case 'ArrowLeft':
      return at <= 0 ? length - 1 : at - 1;
    case 'Home':
      return 0;
    case 'End':
      return length - 1;
    default:
      return null;
  }
}

/** The list with the item at `from` moved to `to`. */
function movedTo<T>(list: readonly T[], from: number, to: number): readonly T[] {
  const rest = list.filter((_, i) => i !== from);
  return [...rest.slice(0, to), list[from], ...rest.slice(to)];
}
