import { FeatureService } from '@core/features/feature.service';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { switchMap } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { I18nMap, Uuid } from '@core/api/models';
import { resolveI18n, sameI18n } from '@shared/forms/i18n-text';
import {
  ButtonComponent,
  ContentLangState,
  ContentLangSwitchComponent,
  FabComponent,
  IconComponent,
  MEDIA,
  mediaQuery,
  PageHeaderComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  FormEditorViewComponent,
  type RuleDraft,
  formEditorValid,
  toDraft,
  toRule,
} from '@stupa-makers/ui-kit/views/form-editor';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { AdminApiService } from '../admin-api.service';
import type { SignatureRow } from '../admin.models';
import { VersionHistoryComponent } from '../version-history/version-history.component';
import {
  type QuestionGroup,
  type QuestionPos,
  groupsFromFields,
  groupsToFields,
  normalizeFormField,
} from '../form-field.util';
import { injectPanePage } from '../pane-page';

/**
 * Form editor page. The body (the outline, the question cards, the form card, the rules, the
 * preview and the menu of the question types) is the kit view `app-form-editor-view` (kit spec
 * 002278). The page reads the form and the type, saves them, shows the header (title, version,
 * active, content language, preview) and projects the versions into the side column.
 *
 * Each group is one wizard step. On save the groups serialize back into the flat `fields[]`
 * list, with a leading `section` marker per group. The backend and the apply wizard therefore
 * still render one step per group.
 *
 * Wide (`MEDIA.wide`): a pane page. The page does not scroll; each column scrolls inside
 * itself and fades at an end only where more content is. Narrower, the columns stack.
 */
@Component({
  selector: 'app-form-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [ContentLangState],
  imports: [
    ContentLangSwitchComponent,
    FabComponent,
    FormEditorViewComponent,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    VersionHistoryComponent,
    PageHeaderComponent,
    BreadcrumbsComponent,
    RowMenuComponent,
    StatusTextComponent,
  ],
  host: { '[class.fe-pane]': 'wide()', '[class.pane-page]': 'wide()' },
  templateUrl: './form-editor.component.html',
  styleUrl: './form-editor.component.scss',
})
export class FormEditorComponent {
  protected readonly contentLang = inject(ContentLangState);
  private readonly api = inject(AdminApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  /** "Mit Budget" shows only while `Budget` is on (spec 000761). */
  protected readonly budgetOn = inject(FeatureService).isOn('budget');

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
  /** The Antrag PDF of this type ends with the signature section (spec 000888). */
  protected readonly pdfSignatures = signal(false);
  /** The signature rows of the Antrag PDF, in order (spec 003005). */
  protected readonly signatureRows = signal<readonly SignatureRow[]>([]);
  /** "Anhang Pflicht": an Antrag of this type needs a file (spec 001732). */
  protected readonly attachmentRequired = signal(false);
  /** The rules across fields (spec 001670); the logic stays text while it is typed. */
  protected readonly rules = signal<readonly RuleDraft[]>([]);
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

  /** The group whose cards show in the middle column. */
  protected readonly activeGroup = signal(0);
  /** The selected question: outlined card, highlighted outline row. */
  protected readonly selected = signal<QuestionPos | null>(null);

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
    const discard: RowMenuItem = {
      id: 'discard',
      label: this.i18n.translate('action.discard'),
      icon: 'undo',
    };
    return [{ items: [...(this.hasVersion() ? [toggle] : []), preview, ...(this.dirty() ? [discard] : [])] }];
  });

  /** Original type state. A save patches the type only after a change. */
  private readonly originalType = signal({
    title: { de: '', en: '' } as I18nMap,
    hasBudget: false,
    pdfSignatures: false,
    signatureRows: '[]',
    attachmentRequired: false,
    cmpRequired: false,
    cmpMinCount: 2,
  });
  /** The questions and the description as the server has them (JSON), for `dirty`. */
  private readonly savedForm = signal<string | null>(null);
  /** The questions and the description as the editor has them (JSON). */
  private readonly formSnapshot = computed(() =>
    JSON.stringify({ groups: this.groups(), description: this.description(), rules: this.rules() }),
  );
  /** The type differs from the server: a save patches it before the new form version. */
  private readonly typeChanged = computed(() => {
    const o = this.originalType();
    return (
      !sameI18n(this.title(), o.title) ||
      this.hasBudget() !== o.hasBudget ||
      this.pdfSignatures() !== o.pdfSignatures ||
      JSON.stringify(this.signatureRows()) !== o.signatureRows ||
      this.attachmentRequired() !== o.attachmentRequired ||
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

  /** The form can be saved; the view shows each problem. */
  protected readonly formValid = computed(() => formEditorValid(this.groups(), this.rules()));

  constructor() {
    injectPanePage(this.wide);
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
          this.pdfSignatures.set(t.pdfSignatures ?? false);
          this.signatureRows.set(t.signatureRows ?? []);
          this.attachmentRequired.set(t.attachmentRequired ?? false);
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
        this.rules.set((draft.rules ?? []).map(toDraft));
        this.active.set(draft.active ?? false);
        this.hasVersion.set(!!draft.formVersionId);
        this.formVersion.set(draft.version ?? null);
        this.savedForm.set(this.formSnapshot());
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  /** "Verwerfen": read the stored form and type again (§ui-kit:000635). */
  protected discard(): void {
    const id = this.typeId();
    if (id) this.load(id);
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
        this.toast.show(
          this.i18n.translate(next ? 'admin.forms.activated' : 'admin.forms.deactivated'),
          'success',
        );
      },
      error: () => {
        this.togglingActive.set(false);
        this.toast.show(this.i18n.translate('admin.forms.actionFailed'), 'error');
      },
    });
  }

  protected resolved(map: I18nMap | undefined): string {
    return map ? resolveI18n(map, this.i18n.uiLocale()) : '';
  }

  /** An action of the ⋮ menu of the header (phone). */
  protected onHeaderMenu(item: RowMenuItem): void {
    switch (item.id) {
      case 'toggleActive':
        return this.toggleActive();
      case 'preview':
        return this.preview.set(!this.preview());
      case 'discard':
        return this.discard();
      default:
        return;
    }
  }

  /** The type fields of the editor are now the state of the server. */
  private keepTypeAsSaved(): void {
    this.originalType.set({
      title: { ...this.title() },
      hasBudget: this.hasBudget(),
      pdfSignatures: this.pdfSignatures(),
      signatureRows: JSON.stringify(this.signatureRows()),
      attachmentRequired: this.attachmentRequired(),
      cmpRequired: this.cmpRequired(),
      cmpMinCount: this.cmpMinCount(),
    });
  }

  protected save(): void {
    const id = this.typeId();
    if (!this.formValid() || !id || this.saving()) {
      this.toast.show(this.i18n.translate('admin.common.invalid'), 'error');
      return;
    }
    const flat = groupsToFields(this.groups());
    const normalized = flat.map(normalizeFormField);
    const description: I18nMap = { ...this.description() };
    const rules = this.rules().map(toRule);
    const snapshot = this.formSnapshot();
    this.saving.set(true);

    const save$ = this.typeChanged()
      ? this.api
          .updateApplicationType(id, {
            name: { ...this.title() },
            hasBudget: this.hasBudget(),
            pdfSignatures: this.pdfSignatures(),
            signatureRows: filledRows(this.signatureRows()),
            attachmentRequired: this.attachmentRequired(),
            comparisonOffers: {
              required: this.cmpRequired(),
              minCount: this.cmpMinCount(),
              thresholdAmount: this.cmpThreshold,
              as: this.cmpAs,
            },
          })
          .pipe(switchMap(() => this.api.createFormVersion(id, normalized, description, rules)))
      : this.api.createFormVersion(id, normalized, description, rules);

    save$.subscribe({
      next: () => {
        this.saving.set(false);
        this.keepTypeAsSaved();
        this.savedForm.set(snapshot);
        this.active.set(true);
        this.hasVersion.set(true);
        this.toast.show(this.i18n.translate('admin.common.saved'), 'success');
        this.history()?.reload();
      },
      error: () => {
        this.saving.set(false);
        this.toast.show(this.i18n.translate('admin.common.saveFailed'), 'error');
      },
    });
  }
}

/** The signature rows that the server takes: both texts given, trimmed (spec 003005). */
function filledRows(rows: readonly SignatureRow[]): readonly SignatureRow[] {
  return rows
    .map((r) => ({ label: r.label.trim(), signer: r.signer.trim() }))
    .filter((r) => r.label !== '' && r.signer !== '');
}
