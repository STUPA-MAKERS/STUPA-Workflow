import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  ApplicationType,
  EffectiveForm,
  FormFieldDef,
  NewApplication,
  ProblemDetail,
  Uuid,
} from '@core/api/models';
import { AnswerViewComponent } from '@shared/forms/answer-view/answer-view.component';
import { resolveI18n } from '@shared/forms/i18n-text';
import { toFormlyFields, toFormlySections } from '@shared/forms/formly-mapper';
import { applyServerErrors, clearServerErrors } from '@shared/forms/server-errors';
import { FieldGroupComponent, FieldRowComponent } from '@shared/ui/field-group/field-group.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { renderMarkdown } from '../meetings/meetings.util';
import {
  BadgeComponent,
  ButtonComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  MEDIA,
  StepperComponent,
  ToastService,
  type Step,
} from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../layout/media-query';
import { AltchaComponent } from './altcha.component';
import { DraftAttachmentsService } from './draft-attachments.service';
import { DraftFilesComponent } from './draft-files/draft-files.component';
import { FormlyDraftFilesType } from './draft-files/formly-draft-files.type';

/** The steps of the wizard. `contact` drops out for a signed-in user without PII fields. */
export type StepKey = 'type' | 'details' | 'contact' | 'review';

/** The autosave of one application type (`sessionStorage`, this tab). */
interface StoredAnswers {
  v: 1;
  model: Record<string, unknown>;
  step: StepKey;
}

/** The key prefix of the autosave per application type. */
export const DRAFT_PREFIX = 'ap.draft.';
/** The key of the application type of the last autosave. */
export const DRAFT_LAST_TYPE = 'ap.draft.lastType';
/** The wait after the last change before the autosave writes. */
const AUTOSAVE_DELAY_MS = 400;

const STEP_TITLE: Record<StepKey, TranslationKey> = {
  type: 'apply.type.title',
  details: 'apply.details.title',
  contact: 'apply.contact.title',
  review: 'apply.review.title',
};

const STEP_LABEL: Record<StepKey, TranslationKey> = {
  type: 'apply.steps.type',
  details: 'apply.steps.details',
  contact: 'apply.steps.contact',
  review: 'apply.steps.review',
};

/**
 * Public application wizard (board Antrag-stellen).
 *
 * Layout: at the start a column with the title, the purpose, the vertical stepper (done
 * steps take a click back) and the autosave note; beside it the sheet "Schritt n von N ·
 * <Typ>" with the step and a bar with "Entwurf verwerfen", "Zurück" and "Weiter" or
 * "Antrag absenden". On a phone the column keeps only the title; the sheet header names
 * the step.
 *
 * Steps:
 * 1. Antragsart: the active types; the configured info text below.
 * 2. Angaben: every section of the effective form in one grid (`toFormlySections`),
 *    without the PII fields. A `file` field uploads its files as drafts; the block
 *    "Anhänge" below takes any other file (Z4, `DraftAttachmentsService`).
 * 3. Kontakt: e-mail and name of a guest, plus the PII fields of the form (for example
 *    the IBAN). A signed-in user sees the account instead; without PII fields the step
 *    drops out.
 * 4. Prüfen & absenden: the answers (`app-answer-view`), the contact, the files, and the
 *    ALTCHA of a guest.
 *
 * All forms stay in the page (only the current one shows), so the submit checks every
 * field even after a restore jumped over a step.
 *
 * Autosave: the answers go into `sessionStorage` per type (this tab only, as before
 * the redesign), WITHOUT the contact step, the PII fields and the file fields. A
 * storage that throws only ends the autosave. The submit and "Entwurf verwerfen" clear
 * the autosave of every type. The draft token of the files also stays in
 * `sessionStorage` (see the service). The values of the file fields come back from
 * the draft files, which survive a reload in the same tab.
 *
 * A type switch keeps the general files ("Anhänge") but deletes the files of the file
 * fields that the new form does not have: the server would bind them with a field
 * reference that the new form does not know.
 */
@Component({
  selector: 'app-apply-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SkeletonComponent,
    ReactiveFormsModule,
    FormlyForm,
    AnswerViewComponent,
    FieldGroupComponent,
    FieldRowComponent,
    BadgeComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    StepperComponent,
    AltchaComponent,
    DraftFilesComponent,
    TranslatePipe,
  ],
  providers: [DraftAttachmentsService],
  templateUrl: './apply-wizard.component.html',
  styleUrl: './apply-wizard.component.scss',
})
export class ApplyWizardComponent {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly branding = inject(BrandingService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly drafts = inject(DraftAttachmentsService);
  protected readonly phone = mediaQuerySignal(MEDIA.phone);

  /**
   * True when a principal is logged in. The account then gives the identity: no e-mail
   * field and no ALTCHA.
   */
  protected readonly loggedIn = this.auth.isAuthenticated;

  readonly types = signal<ApplicationType[]>([]);
  readonly typeId = signal<Uuid | null>(null);
  readonly effForm = signal<EffectiveForm | null>(null);
  readonly activeIndex = signal(0);
  readonly loadingForm = signal(false);
  readonly submitting = signal(false);
  readonly altchaSolution = signal<string | null>(null);
  /** Whether an anonymous submission needs an Altcha solution (false ⇒ Altcha off). */
  readonly altchaRequired = signal(true);
  /** The confirmation of "Entwurf verwerfen" is open. */
  readonly confirmDiscard = signal(false);
  /** The autosave wrote at least once (the note shows). */
  readonly saved = signal(false);
  /** Counts the failed submits: a new value draws a new ALTCHA widget. */
  readonly altchaRound = signal(0);

  /**
   * Shared Formly model of all steps.
   *
   * Formly needs a stable object reference for `[model]`, so it writes each answer into
   * the same object. A plain field would therefore stay invisible to the signal graph.
   * The signal keeps the reference but reports every write: `equal` always says "not
   * equal", so {@link touchModel} notifies its readers although the object is the same
   * one.
   */
  private readonly modelSignal = signal<Record<string, unknown>>({}, { equal: () => false });

  /** Shared Formly model of all steps (stable reference). */
  get model(): Record<string, unknown> {
    return this.modelSignal();
  }
  set model(next: Record<string, unknown>) {
    this.modelSignal.set(next);
  }

  /** The model as a signal, for the review. */
  protected readonly answers = computed(() => ({ ...this.modelSignal() }));

  readonly contactForm = new FormGroup({
    email: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.email],
    }),
    name: new FormControl('', { nonNullable: true }),
  });

  /** The Formly fields of the step "Angaben" and of the PII part of "Kontakt". */
  readonly detailsFields = signal<FormlyFieldConfig[]>([]);
  readonly piiFields = signal<FormlyFieldConfig[]>([]);
  detailsForm = this.trackedGroup();
  piiForm = this.trackedGroup();

  /** The PII fields of the form: they belong to "Kontakt" and stay out of the autosave. */
  private readonly piiDefs = computed<FormFieldDef[]>(() =>
    (this.effForm()?.sections ?? []).flatMap((s) =>
      s.fields.filter((f) => f.isPII && f.type !== 'section' && f.type !== 'markdown'),
    ),
  );
  /**
   * The fields of "Kontakt": the PII fields, plus the display texts of their sections
   * (for example "Die Auszahlung geht an dieses Konto." above the IBAN), in form order.
   */
  private readonly contactDefs = computed<FormFieldDef[]>(() => {
    const pii = new Set(this.piiDefs().map((f) => f.key));
    return (this.effForm()?.sections ?? []).flatMap((s) =>
      s.fields.some((f) => pii.has(f.key))
        ? s.fields.filter((f) => pii.has(f.key) || f.type === 'markdown')
        : [],
    );
  });
  /** The `file` fields: their values are draft ids of this tab, not for the autosave. */
  private readonly fileKeys = computed<Set<string>>(
    () =>
      new Set(
        (this.effForm()?.sections ?? [])
          .flatMap((s) => s.fields)
          .filter((f) => f.type === 'file')
          .map((f) => f.key),
      ),
  );

  /** The steps in order. */
  readonly stepKeys = computed<StepKey[]>(() => {
    const contact = !this.loggedIn() || this.piiDefs().length > 0;
    return contact ? ['type', 'details', 'contact', 'review'] : ['type', 'details', 'review'];
  });

  readonly currentStep = computed<StepKey>(
    () => this.stepKeys()[this.activeIndex()] ?? 'review',
  );

  private readonly typeName = computed(
    () => this.types().find((t) => t.id === this.typeId())?.name ?? '',
  );

  /** The steps of the stepper: label and the second line. */
  readonly steps = computed<Step[]>(() => {
    // Read the locale so the labels follow a language switch.
    this.i18n.locale();
    return this.stepKeys().map((key) => ({
      label: this.i18n.translate(STEP_LABEL[key]),
      hint: this.stepHint(key),
    }));
  });

  /** "Schritt 2 von 4 · Förderantrag". */
  readonly stepLine = computed(() => {
    const line = this.i18n.translate('apply.stepOf', {
      n: this.activeIndex() + 1,
      total: this.stepKeys().length,
    });
    const type = this.activeIndex() > 0 ? this.typeName() : '';
    return type ? `${line} · ${type}` : line;
  });

  readonly stepTitle = computed(() => this.i18n.translate(STEP_TITLE[this.currentStep()]));

  /** The account in the step "Kontakt" of a signed-in user. */
  readonly account = computed(() => {
    const p = this.auth.principal();
    return { name: this.auth.displayName(), email: p?.email ?? '' };
  });

  /** The e-mail of the review: the account or the contact field. */
  readonly reviewEmail = computed(() =>
    this.loggedIn() ? this.account().email || this.account().name : this.contactForm.controls.email.value,
  );

  /** The context of `visibleIf` and `compute`, as on the server. */
  readonly formContext = computed(() => ({ has_budget: this.effForm()?.hasBudget ?? false }));

  /** Configured info text below the type selection — markdown, per language. */
  readonly applyInfoHtml = computed(() => {
    const text = resolveI18n(this.branding.freetexts().applyInfo ?? null, this.i18n.locale()).trim();
    return text ? renderMarkdown(text) : '';
  });

  readonly canSubmit = computed(() => {
    // Read the model, so the value follows each answer.
    this.modelSignal();
    return (
      (this.loggedIn() || !this.altchaRequired() || this.altchaSolution() !== null) &&
      (this.loggedIn() || this.contactForm.valid) &&
      this.detailsForm.valid &&
      this.piiForm.valid &&
      !this.drafts.busy() &&
      !this.drafts.hasFailed()
    );
  });

  private autosaveTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // Load the (cached) session, so a signed-in user gets the account as contact. /apply
    // is public.
    this.auth.ensureLoaded().subscribe();
    this.api.applicationTypes().subscribe({
      next: (t) => {
        const active = t.filter((x) => x.active);
        this.types.set(active);
        // A link that names a type (`/apply?type=…`, the start page) picks it. Else pick
        // up the type of the last autosave on this device.
        const wanted = [
          this.route.snapshot.queryParamMap.get('type'),
          readStorage(DRAFT_LAST_TYPE),
        ].find((id) => !!id && active.some((x) => x.id === id));
        if (wanted) this.selectType(wanted);
      },
      error: () => this.toast.error(this.i18n.translate('apply.error.typesLoad')),
    });
    this.contactForm.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.touchModel());

    // Autosave: a change of the answers or the step writes after a short pause.
    effect(() => {
      this.modelSignal();
      this.activeIndex();
      untracked(() => this.scheduleAutosave());
    });
    this.destroyRef.onDestroy(() => {
      if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    });
  }

  selectType(id: Uuid): void {
    if (this.typeId() === id) return;
    this.typeId.set(id);
    this.loadForm(id);
  }

  private loadForm(id: Uuid): void {
    this.loadingForm.set(true);
    this.api.effectiveForm(id).subscribe({
      next: (eff) => {
        this.model = {};
        this.effForm.set(eff);
        this.buildFields(eff);
        this.restoreDraft(id);
        this.syncFileFields();
        this.loadingForm.set(false);
      },
      error: () => {
        this.loadingForm.set(false);
        this.toast.error(this.i18n.translate('apply.error.formLoad'));
      },
    });
  }

  /**
   * Match the draft files to the file fields of the current form. The files of a field
   * that the form does not have go (a type switch); each file field gets the ids of its
   * files as value, because the autosave leaves them out.
   */
  private syncFileFields(): void {
    const keys = this.fileKeys();
    void this.drafts.scopeToFields(keys);
    for (const key of keys) {
      const ids = this.drafts
        .filesOf(key)
        .filter((f) => !f.failed)
        .map((f) => f.id);
      if (ids.length) this.model[key] = ids;
    }
    this.touchModel();
  }

  /** Build the fields of "Angaben" and of the PII part of "Kontakt". */
  private buildFields(eff: EffectiveForm): void {
    const lang = this.i18n.locale();
    const ctx = this.formContext();
    const contact = this.contactDefs();
    const details = toFormlySections(eff.sections, lang, ctx, {
      omitKeys: contact.map((f) => f.key),
    });
    // A `file` field takes its files as drafts of this wizard (Z4).
    const files = this.fileKeys();
    for (const field of details[0]?.fieldGroup ?? []) {
      if (typeof field.key === 'string' && files.has(field.key)) {
        field.type = FormlyDraftFilesType;
        field.className = 'fe-full';
      }
    }
    this.detailsFields.set(details);
    this.piiFields.set(
      contact.length
        ? [
            {
              fieldGroupClassName: 'fe-grid',
              fieldGroup: toFormlyFields(contact, lang, ctx).map((f, i) => ({
                ...f,
                className: contact[i].type === 'markdown' ? 'fe-full' : 'fe-half',
              })),
            },
          ]
        : [],
    );
    this.detailsForm = this.trackedGroup();
    this.piiForm = this.trackedGroup();
  }

  /**
   * A form group that reports every answer to the signal graph.
   *
   * Formly writes the value into {@link model} from the subscription of the single
   * control. Angular emits the value of the control before the value of the group, so
   * the model already holds the new answer when this handler runs.
   */
  private trackedGroup(): FormGroup {
    const form = new FormGroup({});
    form.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.touchModel());
    return form;
  }

  /** Tell the readers of {@link model} that Formly changed the object. */
  private touchModel(): void {
    this.modelSignal.update((m) => m);
  }

  /** The step is complete; else it shows its errors and gives false. */
  private checkStep(step: StepKey): boolean {
    switch (step) {
      case 'type':
        return this.effForm() !== null;
      case 'details':
        if (this.drafts.busy()) {
          this.toast.show(this.i18n.translate('apply.files.wait'));
          return false;
        }
        return this.checkForm(this.detailsForm);
      case 'contact':
        if (!this.loggedIn() && this.contactForm.invalid) {
          this.contactForm.markAllAsTouched();
          this.revealError();
          return false;
        }
        return this.checkForm(this.piiForm);
      default:
        return true;
    }
  }

  private checkForm(form: FormGroup): boolean {
    if (form.valid) return true;
    form.markAllAsTouched();
    this.toast.error(this.i18n.translate('apply.error.invalid'));
    this.revealError();
    return false;
  }

  next(): void {
    if (!this.checkStep(this.currentStep())) return;
    this.goTo(Math.min(this.activeIndex() + 1, this.stepKeys().length - 1));
  }

  prev(): void {
    this.goTo(Math.max(this.activeIndex() - 1, 0));
  }

  /** A click on a done step of the stepper. */
  goToStep(index: number): void {
    if (index < this.activeIndex()) this.goTo(index);
  }

  private goTo(index: number): void {
    this.activeIndex.set(index);
    window.scrollTo({ top: 0 });
  }

  onAltchaSolved(solution: string): void {
    this.altchaSolution.set(solution);
  }

  /** Altcha is disabled server-side (404) → require no solution. */
  onAltchaUnavailable(): void {
    this.altchaRequired.set(false);
  }

  submit(): void {
    if (!this.canSubmit() || this.submitting()) return;
    const typeId = this.typeId();
    if (!typeId) return;
    const altcha = this.altchaSolution();
    const ids = this.drafts.attachmentIds();
    const token = this.drafts.token();
    const payload: NewApplication = {
      typeId,
      data: this.submitData(),
      // Logged in: the backend derives identity/Altcha from the account.
      applicantEmail: this.loggedIn() ? null : this.contactForm.controls.email.value,
      applicantName: this.loggedIn() ? null : this.contactForm.controls.name.value || null,
      lang: this.i18n.locale(),
      altcha: this.loggedIn() ? null : altcha,
      attachmentIds: ids,
      draftToken: ids.length ? token : null,
    };

    this.submitting.set(true);
    clearServerErrors(this.detailsFields());
    clearServerErrors(this.piiFields());
    this.api.createApplication(payload).subscribe({
      next: (created) => {
        this.clearAutosave();
        this.drafts.clear();
        this.submitting.set(false);
        void this.router.navigate(['/apply/confirmation'], {
          queryParams: { id: created.applicationId },
        });
      },
      error: (err: { status?: number; error?: ProblemDetail | null }) => {
        this.submitting.set(false);
        // A solution is good for one request: the next submit needs a new one.
        this.altchaSolution.set(null);
        this.altchaRound.update((n) => n + 1);
        if (err.status === 422) this.onInvalid(err.error ?? null);
        else this.toast.error(err.error?.detail ?? this.i18n.translate('apply.error.submit'));
      },
    });
  }

  /** The answers to send: file fields keep only the files the server still holds. */
  private submitData(): Record<string, unknown> {
    const data: Record<string, unknown> = { ...this.model };
    const usable = new Set(this.drafts.attachmentIds());
    for (const key of this.fileKeys()) {
      const value = data[key];
      if (!Array.isArray(value)) continue;
      const kept = value.filter((id) => typeof id === 'string' && usable.has(id));
      data[key] = kept.length ? kept : null;
    }
    return data;
  }

  /**
   * A 422 of the submit. Lost files get their mark and the applicant goes back to
   * "Angaben" to upload them again. Field errors go onto the fields and the wizard
   * opens the first step with one.
   */
  private onInvalid(problem: ProblemDetail | null): void {
    const lost = this.drafts.markFailed(problem);
    if (lost.length) {
      this.dropFileRefs(new Set(lost));
      this.toast.error(this.i18n.translate('apply.files.error.lost'));
      this.goTo(this.stepKeys().indexOf('details'));
      return;
    }
    const errors = problem?.errors ?? [];
    const t = (key: TranslationKey) => this.i18n.translate(key);
    const inDetails = errors.length > 0 && applyServerErrors(this.detailsFields(), errors, t);
    const inPii = errors.length > 0 && applyServerErrors(this.piiFields(), errors, t);
    if (inDetails || inPii) {
      this.toast.error(this.i18n.translate('apply.error.invalid'));
      this.goTo(this.stepKeys().indexOf(inDetails ? 'details' : 'contact'));
      this.revealError();
      return;
    }
    this.toast.error(problem?.detail ?? this.i18n.translate('apply.error.submit'));
  }

  /** Take lost files out of the values of the file fields. */
  private dropFileRefs(lost: Set<string>): void {
    for (const key of this.fileKeys()) {
      const value = this.model[key];
      if (!Array.isArray(value)) continue;
      const kept = value.filter((id) => !lost.has(id as string));
      this.model[key] = kept.length ? kept : null;
      this.detailsForm.get(key)?.setValue(this.model[key]);
    }
    this.touchModel();
  }

  /** "Entwurf verwerfen": answers, contact, files and autosave; back to step 1. */
  async discardDraft(): Promise<void> {
    this.confirmDiscard.set(false);
    this.clearAutosave();
    this.model = {};
    this.contactForm.reset();
    this.altchaSolution.set(null);
    const eff = this.effForm();
    if (eff) this.buildFields(eff);
    this.activeIndex.set(0);
    this.saved.set(false);
    await this.drafts.discard();
  }

  // --- autosave ------------------------------------------------------------------

  private draftKey(): string | null {
    const id = this.typeId();
    return id ? `${DRAFT_PREFIX}${id}` : null;
  }

  private scheduleAutosave(): void {
    if (!this.draftKey()) return;
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    this.autosaveTimer = setTimeout(() => {
      this.autosaveTimer = null;
      this.persistDraft();
    }, AUTOSAVE_DELAY_MS);
  }

  /**
   * Write the autosave: the answers without the PII and file fields, and the step. The
   * contact step is never stored. A storage that throws ends the autosave quietly.
   *
   * Without an answer, there is no draft: the autosave of the type goes and the note
   * "saved" goes. Thus a type pick alone and an "Entwurf verwerfen" store nothing (the
   * autosave effect runs after the discard and sees the empty model).
   */
  persistDraft(): void {
    const key = this.draftKey();
    const typeId = this.typeId();
    if (!key || !typeId || !this.effForm()) return;
    const skip = new Set([...this.piiDefs().map((f) => f.key), ...this.fileKeys()]);
    const model: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(this.model)) {
      if (!skip.has(k)) model[k] = v;
    }
    if (!Object.values(model).some(hasAnswer)) {
      this.dropDraft(key, typeId);
      return;
    }
    const draft: StoredAnswers = { v: 1, model, step: this.currentStep() };
    try {
      sessionStorage.setItem(key, JSON.stringify(draft));
      sessionStorage.setItem(DRAFT_LAST_TYPE, typeId);
      this.saved.set(true);
    } catch {
      /* storage blocked: the autosave is best effort */
    }
  }

  /** Remove the autosave of one type, and the last type when it points to this type. */
  private dropDraft(key: string, typeId: Uuid): void {
    this.saved.set(false);
    try {
      sessionStorage.removeItem(key);
      if (sessionStorage.getItem(DRAFT_LAST_TYPE) === typeId) {
        sessionStorage.removeItem(DRAFT_LAST_TYPE);
      }
    } catch {
      /* storage blocked: nothing to remove */
    }
  }

  private restoreDraft(id: Uuid): void {
    const raw = readStorage(`${DRAFT_PREFIX}${id}`);
    if (!raw) return;
    let draft: Partial<StoredAnswers>;
    try {
      draft = JSON.parse(raw) as Partial<StoredAnswers>;
    } catch {
      return; // a broken entry: ignore it
    }
    if (draft.model && typeof draft.model === 'object') {
      const skip = new Set([...this.piiDefs().map((f) => f.key), ...this.fileKeys()]);
      for (const [k, v] of Object.entries(draft.model)) {
        if (!skip.has(k)) this.model[k] = v;
      }
      this.touchModel();
      this.saved.set(true);
    }
    // Go back to the stored step, but never past an empty contact step: the contact
    // is not stored.
    const keys = this.stepKeys();
    let target = draft.step ? keys.indexOf(draft.step) : -1;
    if (target < 0) return;
    const contact = keys.indexOf('contact');
    if (contact >= 0 && target > contact && !this.loggedIn() && this.contactForm.invalid) {
      target = contact;
    }
    this.activeIndex.set(target);
  }

  /** Remove the autosave of every type and the last type. */
  private clearAutosave(): void {
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    this.autosaveTimer = null;
    try {
      const keys: string[] = [];
      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i);
        if (key?.startsWith(DRAFT_PREFIX)) keys.push(key);
      }
      for (const key of keys) sessionStorage.removeItem(key);
    } catch {
      /* storage blocked: nothing to clear */
    }
  }

  // --- helpers -------------------------------------------------------------------

  /** The second line of a step in the stepper. */
  private stepHint(key: StepKey): string {
    switch (key) {
      case 'type':
        return this.typeName();
      case 'details': {
        const contact = new Set(this.contactDefs().map((f) => f.key));
        const labels = (this.effForm()?.sections ?? [])
          .filter((s) => s.fields.some((f) => !contact.has(f.key) && f.type !== 'section'))
          .map((s) => resolveI18n(s.label, this.i18n.locale()))
          .filter(Boolean);
        return this.list(labels);
      }
      case 'contact': {
        const parts = this.loggedIn()
          ? []
          : [this.i18n.translate('apply.contact.name'), this.i18n.translate('apply.contact.email')];
        for (const f of this.piiDefs()) parts.push(resolveI18n(f.label, this.i18n.locale()));
        return this.list(parts);
      }
      default:
        return this.i18n.translate('apply.steps.reviewHint');
    }
  }

  /** "A, B und C" in the active language. */
  private list(parts: string[]): string {
    if (parts.length < 2) return parts[0] ?? '';
    return new Intl.ListFormat(this.i18n.formatLocale(), { type: 'conjunction' }).format(parts);
  }

  /** Scroll the first field with an error into view, after the form drew it. */
  private revealError(): void {
    setTimeout(() => {
      const el = document.querySelector<HTMLElement>(
        '.wz__step:not([hidden]) [aria-invalid="true"], .wz__step:not([hidden]) [role="alert"]',
      );
      el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    });
  }
}

/** Read a `sessionStorage` entry; a storage that throws gives null. */
function readStorage(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

/**
 * The value holds an answer. Empty text, an empty list, an object without an answer,
 * null and false (an unset checkbox) are the state of a new form, so they hold none.
 */
function hasAnswer(value: unknown): boolean {
  if (value === null || value === undefined || value === false) return false;
  if (typeof value === 'string') return value.trim() !== '';
  if (Array.isArray(value)) return value.some(hasAnswer);
  if (typeof value === 'object') return Object.values(value).some(hasAnswer);
  return true;
}
