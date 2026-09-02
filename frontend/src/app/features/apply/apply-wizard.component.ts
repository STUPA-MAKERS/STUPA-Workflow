import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import {
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { Router } from '@angular/router';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  ApplicationType,
  EffectiveForm,
  FormFieldDef,
  NewApplication,
  ProblemDetail,
  Uuid,
} from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import { renderMarkdown } from '../meetings/meetings.util';
import { toFormlyFields } from '@shared/forms/formly-mapper';
import { isFieldVisible } from '@shared/forms/jsonlogic';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { CardComponent } from '@stupa-makers/ui-kit';
import { InputComponent } from '@stupa-makers/ui-kit';
import { StepperComponent, type Step } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { AltchaComponent } from './altcha.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

interface WizardSection {
  key: string;
  label: string;
  fields: FormlyFieldConfig[];
  form: FormGroup;
}

interface SummaryRow {
  label: string;
  value: string;
}

type StepKind = 'type' | 'contact' | 'section' | 'review';

const DRAFT_PREFIX = 'ap.draft.';

/**
 * Public application wizard.
 *
 * The steps run in this order: application type, contact, form sections, review with
 * Altcha and submit. Formly builds the form sections from the effective definition.
 * That definition holds the `visibleIf` and `computed` rules plus the extra fields of
 * the budget pot. The wizard saves the progress per application type in the browser
 * (autosave).
 */
@Component({
  selector: 'app-apply-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SkeletonComponent, 
    ReactiveFormsModule,
    FormlyForm,
    ButtonComponent,
    CardComponent,
    InputComponent,
    StepperComponent,
    AltchaComponent,
    TranslatePipe,
  ],
  templateUrl: './apply-wizard.component.html',
  styleUrl: './apply-wizard.component.scss',
})
export class ApplyWizardComponent {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  /**
   * True when a principal is logged in. The wizard then skips the contact step and
   * Altcha. The identity comes from the account.
   */
  protected readonly loggedIn = this.auth.isAuthenticated;

  readonly types = signal<ApplicationType[]>([]);
  readonly typeId = signal<Uuid | null>(null);
  readonly effForm = signal<EffectiveForm | null>(null);
  readonly sections = signal<WizardSection[]>([]);
  readonly activeIndex = signal(0);
  readonly loadingForm = signal(false);
  readonly submitting = signal(false);
  readonly altchaSolution = signal<string | null>(null);
  /** Whether an anonymous submission needs an Altcha solution (false ⇒ Altcha off). */
  readonly altchaRequired = signal(true);

  /** Shared Formly model across all sections (stable reference). */
  model: Record<string, unknown> = {};

  readonly contactForm = new FormGroup({
    email: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.email],
    }),
    name: new FormControl('', { nonNullable: true }),
  });

  readonly steps = computed<Step[]>(() => {
    const t = (k: Parameters<I18nService['translate']>[0]) => this.i18n.translate(k);
    // Read i18n.locale() so the signal recomputes on language change.
    this.i18n.locale();
    if (!this.effForm()) return [{ label: t('apply.steps.type') }];
    return [
      { label: t('apply.steps.type') },
      ...(this.loggedIn() ? [] : [{ label: t('apply.steps.contact') }]),
      ...this.sections().map((s) => ({ label: s.label })),
      { label: t('apply.steps.review') },
    ];
  });

  /** Index of the first form section: 1 without the contact step (logged in), else 2. */
  private readonly sectionBase = computed(() => (this.loggedIn() ? 1 : 2));

  readonly currentStep = computed<StepKind>(() => {
    const idx = this.activeIndex();
    if (idx === 0) return 'type';
    if (!this.loggedIn() && idx === 1) return 'contact';
    if (idx - this.sectionBase() < this.sections().length) return 'section';
    return 'review';
  });

  readonly currentSection = computed<WizardSection | null>(
    () => this.sections()[this.activeIndex() - this.sectionBase()] ?? null,
  );

  /** Applicant email shown in review: account (logged in) or contact field. */
  readonly reviewEmail = computed(() =>
    this.loggedIn()
      ? (this.auth.principal()?.email ?? this.auth.displayName())
      : this.contactForm.controls.email.value,
  );

  readonly summary = computed<SummaryRow[]>(() => this.buildSummary());

  /** Configured info text below the type selection — markdown, per language. */
  private readonly applyInfo = signal<Record<string, string> | null>(null);
  readonly applyInfoHtml = computed(() => {
    const text = resolveI18n(this.applyInfo(), this.i18n.locale()).trim();
    return text ? renderMarkdown(text) : '';
  });

  constructor() {
    // Load the (cached) session so the wizard skips the contact step/Altcha for
    // logged-in users. /apply is unprotected.
    this.auth.ensureLoaded().subscribe();
    this.api.applicationTypes().subscribe({
      next: (t) => this.types.set(t.filter((x) => x.active)),
      error: () => this.toast.error(this.i18n.translate('apply.error.typesLoad')),
    });
    // Branding info below the type selection — public endpoint, fault-tolerant.
    this.api.publicSiteConfig().subscribe({
      next: (cfg) => this.applyInfo.set(cfg.branding?.freetexts?.applyInfo ?? null),
      error: () => undefined,
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
        this.effForm.set(eff);
        this.buildSections(eff);
        this.restoreDraft(id);
        this.loadingForm.set(false);
      },
      error: () => {
        this.loadingForm.set(false);
        this.toast.error(this.i18n.translate('apply.error.formLoad'));
      },
    });
  }

  private buildSections(eff: EffectiveForm): void {
    const lang = this.i18n.locale();
    const ctx = { has_budget: Boolean(eff.budgetPotId) };
    this.sections.set(
      eff.sections.map((s) => ({
        key: s.key,
        label: resolveI18n(s.label, lang),
        fields: toFormlyFields(s.fields, lang, ctx),
        form: new FormGroup({}),
      })),
    );
  }

  next(): void {
    const step = this.currentStep();
    if (step === 'type' && !this.typeId()) return;
    if (step === 'contact' && this.contactForm.invalid) {
      this.contactForm.markAllAsTouched();
      return;
    }
    if (step === 'section') {
      const form = this.currentSection()?.form;
      if (form && form.invalid) {
        form.markAllAsTouched();
        return;
      }
    }
    this.activeIndex.update((i) => Math.min(i + 1, this.steps().length - 1));
    this.persistDraft();
  }

  prev(): void {
    this.activeIndex.update((i) => Math.max(i - 1, 0));
    this.persistDraft();
  }

  onAltchaSolved(solution: string): void {
    this.altchaSolution.set(solution);
  }

  /** Altcha is disabled server-side (404) → require no solution. */
  onAltchaUnavailable(): void {
    this.altchaRequired.set(false);
  }

  readonly canSubmit = computed(
    () =>
      // A logged-in user needs no Altcha and no contact data. An anonymous user
      // needs both, unless the server has Altcha off.
      (this.loggedIn() || !this.altchaRequired() || this.altchaSolution() !== null) &&
      (this.loggedIn() || this.contactForm.valid) &&
      this.sections().every((s) => s.form.valid),
  );

  submit(): void {
    if (!this.canSubmit() || this.submitting()) return;
    const typeId = this.typeId();
    const altcha = this.altchaSolution();
    if (!typeId) return;
    if (!this.loggedIn() && this.altchaRequired() && !altcha) return;

    const payload: NewApplication = {
      typeId,
      budgetPotId: this.effForm()?.budgetPotId ?? null,
      data: { ...this.model },
      // Logged in: the backend derives identity/Altcha from the account.
      applicantEmail: this.loggedIn() ? null : this.contactForm.controls.email.value,
      applicantName: this.loggedIn() ? null : this.contactForm.controls.name.value || null,
      lang: this.i18n.locale(),
      altcha: this.loggedIn() ? null : altcha,
    };

    this.submitting.set(true);
    this.api.createApplication(payload).subscribe({
      next: (created) => {
        this.clearDraft();
        this.submitting.set(false);
        void this.router.navigate(['/apply/confirmation'], {
          queryParams: { id: created.applicationId },
        });
      },
      error: (err: { error?: ProblemDetail }) => {
        this.submitting.set(false);
        this.toast.error(err.error?.detail ?? this.i18n.translate('apply.error.submit'));
      },
    });
  }

  private draftKey(): string | null {
    const id = this.typeId();
    return id ? `${DRAFT_PREFIX}${id}` : null;
  }

  private persistDraft(): void {
    const key = this.draftKey();
    if (!key) return;
    try {
      sessionStorage.setItem(
        key,
        JSON.stringify({
          model: this.model,
          contact: this.contactForm.getRawValue(),
          activeIndex: this.activeIndex(),
        }),
      );
    } catch {
      /* storage blocked — autosave is best-effort */
    }
  }

  private restoreDraft(id: Uuid): void {
    let raw: string | null = null;
    try {
      raw = sessionStorage.getItem(`${DRAFT_PREFIX}${id}`);
    } catch {
      return;
    }
    if (!raw) return;
    try {
      const draft = JSON.parse(raw) as {
        model?: Record<string, unknown>;
        contact?: { email?: string; name?: string };
        activeIndex?: number;
      };
      if (draft.model) Object.assign(this.model, draft.model);
      if (draft.contact) {
        this.contactForm.patchValue({
          email: draft.contact.email ?? '',
          name: draft.contact.name ?? '',
        });
      }
      // loadForm builds the sections before restoreDraft(), so steps() is complete.
      // Restore the saved step, clamped to the valid range.
      if (typeof draft.activeIndex === 'number' && Number.isFinite(draft.activeIndex)) {
        const max = this.steps().length - 1;
        this.activeIndex.set(Math.min(Math.max(Math.trunc(draft.activeIndex), 0), max));
      }
    } catch {
      /* corrupt draft — ignore */
    }
  }

  discardDraft(): void {
    this.clearDraft();
    this.model = {};
    this.contactForm.reset();
    this.altchaSolution.set(null);
    const eff = this.effForm();
    if (eff) this.buildSections(eff);
    this.activeIndex.set(0);
  }

  private clearDraft(): void {
    const key = this.draftKey();
    if (!key) return;
    try {
      sessionStorage.removeItem(key);
    } catch {
      /* storage blocked — nothing to clear */
    }
  }

  private buildSummary(): SummaryRow[] {
    const eff = this.effForm();
    if (!eff) return [];
    const lang = this.i18n.locale();
    const rows: SummaryRow[] = [];
    for (const section of eff.sections) {
      for (const field of section.fields) {
        if (field.type === 'markdown') continue;
        if (!isFieldVisible(field.visibleIf, this.model)) continue;
        const value = this.formatValue(field, this.model[field.key]);
        if (value !== '') rows.push({ label: resolveI18n(field.label, lang), value });
      }
    }
    return rows;
  }

  private formatValue(field: FormFieldDef, value: unknown): string {
    if (value === null || value === undefined || value === '') return '';
    if (field.type === 'positions') return this.formatPositions(value);
    if (Array.isArray(value)) return value.map((v) => this.optionLabel(field, v)).join(', ');
    if (typeof value === 'boolean')
      return this.i18n.translate(value ? 'common.yes' : 'common.no');
    return this.optionLabel(field, value);
  }

  private optionLabel(field: FormFieldDef, value: unknown): string {
    const opt = field.options?.find((o) => o.value === value);
    return opt ? resolveI18n(opt.label, this.i18n.locale()) : String(value);
  }

  /** Cost positions in review: number of positions + Σ of preferred values. */
  private formatPositions(value: unknown): string {
    if (!Array.isArray(value)) return '';
    let total = 0;
    for (const p of value as { offers?: { value?: number | null; preferred?: boolean }[] }[]) {
      const pref = (p.offers ?? []).find((o) => o.preferred);
      total += pref?.value ?? 0;
    }
    const sum = new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: 'EUR',
    }).format(total);
    return `${value.length} × ${this.i18n.translate('apply.positions.positionValue')} · ${this.i18n.translate('apply.positions.total')}: ${sum}`;
  }
}
