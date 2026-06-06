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
import { I18nService } from '@core/i18n/i18n.service';
import type {
  ApplicationType,
  EffectiveForm,
  FormFieldDef,
  NewApplication,
  ProblemDetail,
  Uuid,
} from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import { toFormlyFields } from '@shared/forms/formly-mapper';
import { isFieldVisible } from '@shared/forms/jsonlogic';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { CardComponent } from '@shared/ui/card/card.component';
import { InputComponent } from '@shared/ui/input/input.component';
import { StepperComponent, type Step } from '@shared/ui/stepper/stepper.component';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AltchaComponent } from './altcha.component';

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
 * Öffentlicher Antrags-Wizard (T-30, flows §1 / requirements N1a).
 * Schritte: Antragsart → Kontakt → Form-Sektionen (aus effektiver Definition via
 * Formly, inkl. `visibleIf`/`computed` + Topf-Extra-Felder) → Prüfen/Altcha/Absenden.
 * Zwischenstand wird je Antragsart lokal gespeichert (Zwischenspeichern).
 */
@Component({
  selector: 'app-apply-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    FormlyForm,
    ButtonComponent,
    CardComponent,
    InputComponent,
    StepperComponent,
    AltchaComponent,
  ],
  templateUrl: './apply-wizard.component.html',
  styleUrl: './apply-wizard.component.scss',
})
export class ApplyWizardComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  readonly types = signal<ApplicationType[]>([]);
  readonly typeId = signal<Uuid | null>(null);
  readonly effForm = signal<EffectiveForm | null>(null);
  readonly sections = signal<WizardSection[]>([]);
  readonly activeIndex = signal(0);
  readonly loadingForm = signal(false);
  readonly submitting = signal(false);
  readonly altchaSolution = signal<string | null>(null);

  /** Geteiltes Formly-Modell über alle Sektionen (stabile Referenz). */
  model: Record<string, unknown> = {};

  readonly contactForm = new FormGroup({
    email: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.email],
    }),
    name: new FormControl('', { nonNullable: true }),
  });

  readonly steps = computed<Step[]>(() => {
    if (!this.effForm()) return [{ label: 'Antragsart' }];
    return [
      { label: 'Antragsart' },
      { label: 'Kontakt' },
      ...this.sections().map((s) => ({ label: s.label })),
      { label: 'Prüfen' },
    ];
  });

  readonly currentStep = computed<StepKind>(() => {
    const idx = this.activeIndex();
    if (idx === 0) return 'type';
    if (idx === 1) return 'contact';
    if (idx - 2 < this.sections().length) return 'section';
    return 'review';
  });

  readonly currentSection = computed<WizardSection | null>(
    () => this.sections()[this.activeIndex() - 2] ?? null,
  );

  readonly summary = computed<SummaryRow[]>(() => this.buildSummary());

  constructor() {
    this.api.applicationTypes().subscribe({
      next: (t) => this.types.set(t.filter((x) => x.active)),
      error: () => this.toast.error('Antragsarten konnten nicht geladen werden.'),
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
        this.toast.error('Formular konnte nicht geladen werden.');
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

  // --- navigation ----------------------------------------------------------
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

  readonly canSubmit = computed(
    () =>
      this.altchaSolution() !== null &&
      this.contactForm.valid &&
      this.sections().every((s) => s.form.valid),
  );

  submit(): void {
    if (!this.canSubmit() || this.submitting()) return;
    const typeId = this.typeId();
    const altcha = this.altchaSolution();
    if (!typeId || !altcha) return;

    const payload: NewApplication = {
      typeId,
      budgetPotId: this.effForm()?.budgetPotId ?? null,
      data: { ...this.model },
      applicantEmail: this.contactForm.controls.email.value,
      applicantName: this.contactForm.controls.name.value || null,
      lang: this.i18n.locale(),
      altcha,
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
        this.toast.error(err.error?.detail ?? 'Antrag konnte nicht gesendet werden.');
      },
    });
  }

  // --- draft (Zwischenspeichern) -------------------------------------------
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
      /* storage gesperrt — Zwischenspeichern ist best-effort */
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
    } catch {
      /* defekter Entwurf — ignorieren */
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
      /* ignore */
    }
  }

  // --- review summary ------------------------------------------------------
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
    if (Array.isArray(value)) return value.map((v) => this.optionLabel(field, v)).join(', ');
    if (typeof value === 'boolean') return value ? 'Ja' : 'Nein';
    return this.optionLabel(field, value);
  }

  private optionLabel(field: FormFieldDef, value: unknown): string {
    const opt = field.options?.find((o) => o.value === value);
    return opt ? resolveI18n(opt.label, this.i18n.locale()) : String(value);
  }
}
