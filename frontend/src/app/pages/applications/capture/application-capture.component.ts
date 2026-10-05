import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, FormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
import type {
  ApplicantCandidate,
  ApplicationType,
  EffectiveForm,
  OnBehalfApplication,
  ProblemDetail,
  Uuid,
} from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { toFormlySections } from '@shared/forms/formly-mapper';
import { applyServerErrors, clearServerErrors } from '@shared/forms/server-errors';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import {
  ButtonComponent,
  DatepickerComponent,
  IconComponent,
  InputComponent,
  SegmentedComponent,
  SelectComponent,
  ToastService,
  type SegmentedOption,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import {
  DRAFT_FILES_STORAGE_KEY,
  DraftAttachmentsService,
} from '../../../features/apply/draft-attachments.service';
import { DraftFilesComponent } from '../../../features/apply/draft-files/draft-files.component';
import { FormlyDraftFilesType } from '../../../features/apply/draft-files/formly-draft-files.type';

/** Who the application is for: an account, or a new person without one. */
export type ApplicantMode = 'account' | 'guest';

/** The `sessionStorage` key of the draft files of the capture (not the wizard's). */
export const CAPTURE_FILES_KEY = 'ap.captureFiles';

/** The wait after the last key stroke before the applicant search asks the server. */
export const APPLICANT_SEARCH_DELAY_MS = 250;
/** The shortest search text; the server answers nothing for a shorter one. */
const APPLICANT_SEARCH_MIN = 2;

/** A plain e-mail check; the server validates the address again. */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * "Antrag erfassen" (#11): capture an application on behalf of an applicant.
 *
 * The form has the pattern of "Buchung hinzufügen" (`booking-form`): a fixed head with
 * the title and the close button, a body of sections that scrolls with a fade, and a
 * fixed foot with "Abbrechen" and the submit. Side by side it fills the detail pane
 * (`layout="pane"`); on a phone a bottom sheet holds it (`layout="sheet"`, the sheet
 * brings the head).
 *
 * Sections:
 * 1. Antragsteller:in: an account from the search (name or e-mail), or "Neue Person"
 *    with name and e-mail (a guest, who gets a personal access link).
 * 2. Antrag: the type, the received date (default today, never in the future) and the
 *    free-text "Eingang" (for example "per PDF").
 * 3. Angaben: the effective form of the type, in the grid and the look of the apply
 *    wizard, and the general files ("Anhänge"), uploaded as drafts like in the wizard.
 *
 * The server validates the data like a normal submission; a 422 goes onto the fields it
 * names. On success the component emits `created` with the new id.
 */
@Component({
  selector: 'app-application-capture',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    FormlyForm,
    TranslatePipe,
    ButtonComponent,
    DatepickerComponent,
    IconComponent,
    InputComponent,
    SegmentedComponent,
    SelectComponent,
    ScrollFadeDirective,
    SkeletonComponent,
    DraftFilesComponent,
  ],
  providers: [
    DraftAttachmentsService,
    { provide: DRAFT_FILES_STORAGE_KEY, useValue: CAPTURE_FILES_KEY },
  ],
  templateUrl: './application-capture.component.html',
  styleUrl: './application-capture.component.scss',
})
export class ApplicationCaptureComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly drafts = inject(DraftAttachmentsService);

  /**
   * `pane`: the detail pane side by side; `page`: the detail alone (one pane at a time,
   * the foot sticks to the viewport); `sheet`: the bottom sheet of a phone.
   */
  readonly layout = input<'pane' | 'page' | 'sheet'>('pane');
  /** The application types; the form offers the active ones. */
  readonly types = input<readonly ApplicationType[]>([]);

  readonly closed = output<void>();
  readonly created = output<Uuid>();

  // --- applicant -----------------------------------------------------------------
  readonly mode = signal<ApplicantMode>('account');
  readonly query = signal('');
  readonly candidates = signal<ApplicantCandidate[]>([]);
  readonly searching = signal(false);
  readonly picked = signal<ApplicantCandidate | null>(null);
  readonly guestName = signal('');
  readonly guestEmail = signal('');
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  private searchSeq = 0;

  // --- application ---------------------------------------------------------------
  readonly typeId = signal('');
  readonly effForm = signal<EffectiveForm | null>(null);
  readonly loadingForm = signal(false);
  readonly today = localToday();
  readonly receivedOn = signal(this.today);
  readonly intake = signal('');
  readonly saving = signal(false);

  readonly fields = signal<FormlyFieldConfig[]>([]);
  form = this.trackedGroup();
  /** The Formly model (stable reference, see the apply wizard). */
  model: Record<string, unknown> = {};
  /** Counts the Formly changes, so `canSubmit` follows the validity of the form. */
  private readonly formTick = signal(0);

  protected readonly modeOptions = computed<SegmentedOption[]>(() => {
    this.i18n.locale();
    return [
      { value: 'account', label: this.i18n.translate('applications.capture.mode.account') },
      { value: 'guest', label: this.i18n.translate('applications.capture.mode.guest') },
    ];
  });

  protected readonly typeOptions = computed<SelectOption[]>(() =>
    this.types()
      .filter((t) => t.active)
      .map((t) => ({ value: t.id, label: t.name })),
  );

  /** The search lists its hits below the field while there are hits. */
  protected readonly suggestOpen = computed(
    () => this.picked() === null && this.candidates().length > 0,
  );
  /** "Keine Treffer": a finished search of two or more characters without a hit. */
  protected readonly noHits = computed(
    () =>
      this.picked() === null &&
      !this.searching() &&
      this.query().trim().length >= APPLICANT_SEARCH_MIN &&
      this.candidates().length === 0,
  );

  protected readonly guestEmailError = computed(() => {
    const email = this.guestEmail().trim();
    return email && !EMAIL.test(email) ? 'applications.capture.emailInvalid' : null;
  });

  protected readonly futureDate = computed(() => this.receivedOn() > this.today);

  private readonly applicantReady = computed(() =>
    this.mode() === 'account'
      ? this.picked() !== null
      : this.guestName().trim() !== '' && EMAIL.test(this.guestEmail().trim()),
  );

  readonly canSubmit = computed(() => {
    this.formTick();
    return (
      this.applicantReady() &&
      this.effForm() !== null &&
      this.receivedOn() !== '' &&
      !this.futureDate() &&
      this.form.valid &&
      !this.drafts.busy() &&
      !this.drafts.hasFailed()
    );
  });

  /** The second line of the head: the chosen applicant, else the hint. */
  protected readonly subtitle = computed(() => {
    const name = this.mode() === 'account' ? this.pickedLabel() : this.guestName().trim();
    return name
      ? this.i18n.translate('applications.capture.subtitleFor', { name })
      : this.i18n.translate('applications.capture.subtitle');
  });

  protected readonly pickedLabel = computed(() => {
    const p = this.picked();
    return p ? candidateLabel(p) : '';
  });

  constructor() {
    this.destroyRef.onDestroy(() => {
      if (this.searchTimer) clearTimeout(this.searchTimer);
    });
  }

  // --- applicant -----------------------------------------------------------------

  setMode(value: string): void {
    this.mode.set(value === 'guest' ? 'guest' : 'account');
  }

  /** The search field: it searches by itself after a short pause. */
  onSearch(text: string): void {
    this.query.set(text);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    const q = text.trim();
    if (q.length < APPLICANT_SEARCH_MIN) {
      this.searchSeq++;
      this.candidates.set([]);
      this.searching.set(false);
      return;
    }
    this.searching.set(true);
    this.searchTimer = setTimeout(() => this.search(q), APPLICANT_SEARCH_DELAY_MS);
  }

  private search(q: string): void {
    const seq = ++this.searchSeq;
    this.api.searchOnBehalfApplicants(q).subscribe({
      next: (hits) => {
        if (seq !== this.searchSeq) return;
        this.candidates.set(hits);
        this.searching.set(false);
      },
      error: () => {
        if (seq !== this.searchSeq) return;
        this.candidates.set([]);
        this.searching.set(false);
      },
    });
  }

  pick(candidate: ApplicantCandidate): void {
    this.picked.set(candidate);
    this.candidates.set([]);
    this.query.set(candidateLabel(candidate));
  }

  clearPick(): void {
    this.picked.set(null);
    this.query.set('');
  }

  /** "Neue Person": the search text moves into the name or the e-mail field. */
  useAsGuest(): void {
    const text = this.query().trim();
    if (EMAIL.test(text)) this.guestEmail.set(text);
    else this.guestName.set(text);
    this.mode.set('guest');
  }

  // --- application ---------------------------------------------------------------

  selectType(id: string): void {
    if (!id || id === this.typeId()) return;
    this.typeId.set(id);
    this.loadingForm.set(true);
    this.api.effectiveForm(id).subscribe({
      next: (eff) => {
        this.model = {};
        this.effForm.set(eff);
        this.buildFields(eff);
        this.loadingForm.set(false);
      },
      error: () => {
        this.effForm.set(null);
        this.fields.set([]);
        this.loadingForm.set(false);
        this.toast.error(this.i18n.translate('apply.error.formLoad'));
      },
    });
  }

  /** The fields of the form, as the wizard draws them; a `file` field takes drafts. */
  private buildFields(eff: EffectiveForm): void {
    const fileKeys = new Set(
      eff.sections
        .flatMap((s) => s.fields)
        .filter((f) => f.type === 'file')
        .map((f) => f.key),
    );
    void this.drafts.scopeToFields(fileKeys);
    const sections = toFormlySections(eff.sections, this.i18n.locale(), {
      has_budget: eff.hasBudget,
    });
    for (const field of sections[0]?.fieldGroup ?? []) {
      if (typeof field.key === 'string' && fileKeys.has(field.key)) {
        field.type = FormlyDraftFilesType;
        field.className = 'fe-full';
      }
    }
    this.form = this.trackedGroup();
    this.fields.set(sections);
  }

  /** A form group that tells `canSubmit` about every change of Formly. */
  private trackedGroup(): FormGroup {
    const form = new FormGroup({});
    form.statusChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.formTick.update((n) => n + 1));
    return form;
  }

  // --- submit --------------------------------------------------------------------

  close(): void {
    void this.drafts.discard();
    this.closed.emit();
  }

  submit(event?: Event): void {
    event?.preventDefault();
    if (this.saving()) return;
    if (!this.canSubmit()) {
      this.form.markAllAsTouched();
      this.toast.error(this.i18n.translate('applications.capture.incomplete'));
      return;
    }
    const ids = this.drafts.attachmentIds();
    const picked = this.mode() === 'account' ? this.picked() : null;
    const payload: OnBehalfApplication = {
      typeId: this.typeId(),
      data: { ...this.model },
      applicantPrincipalId: picked?.id ?? null,
      applicantName: picked ? null : this.guestName().trim(),
      applicantEmail: picked ? null : this.guestEmail().trim(),
      receivedOn: this.receivedOn(),
      intake: this.intake().trim() || null,
      lang: this.i18n.locale(),
      attachmentIds: ids,
      draftToken: ids.length ? this.drafts.token() : null,
    };
    this.saving.set(true);
    clearServerErrors(this.fields());
    this.api.createApplicationOnBehalf(payload).subscribe({
      next: (res) => {
        this.saving.set(false);
        this.drafts.clear();
        this.toast.success(this.i18n.translate('applications.capture.done'));
        this.created.emit(res.applicationId);
      },
      error: (err: { status?: number; error?: ProblemDetail | null }) => {
        this.saving.set(false);
        this.onError(err.status, err.error ?? null);
      },
    });
  }

  /** A 422 goes onto the fields it names; any other error is a toast. */
  private onError(status: number | undefined, problem: ProblemDetail | null): void {
    if (status === 422) {
      this.drafts.markFailed(problem);
      const t = (key: TranslationKey) => this.i18n.translate(key);
      const errors = problem?.errors ?? [];
      if (errors.length && applyServerErrors(this.fields(), errors, t)) {
        this.toast.error(this.i18n.translate('apply.error.invalid'));
        return;
      }
    }
    this.toast.error(problem?.detail ?? this.i18n.translate('applications.capture.error'));
  }
}

/** "Name · e-mail", or the one that exists. */
export function candidateLabel(c: ApplicantCandidate): string {
  return [c.displayName, c.email].filter(Boolean).join(' · ');
}

/** Today in the local timezone as `YYYY-MM-DD`. */
export function localToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
