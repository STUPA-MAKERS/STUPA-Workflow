import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  NoteComponent,
  SelectFieldComponent,
  type SelectOption,
  SkeletonComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import {
  type CdVariantOption,
  type Gremium,
  type GremiumCreateBody,
  type GremiumPublicPreview,
  type GremiumUpdateBody,
  slugify,
} from '../../admin.models';

/** The largest lead time in minutes that the server accepts (30 days). */
export const MAX_DELEGATION_LEAD_MINUTES = 60 * 24 * 30;
/** The limits of `delegationMaxPerDelegate` (`MAX_DELEGATIONS_PER_DELEGATE` of the backend). */
export const MAX_DELEGATIONS_PER_DELEGATE = 20;
export const DEFAULT_DELEGATIONS_PER_DELEGATE = 2;

/** The most delegations per person: empty or invalid gives the default, else 1 to 20. */
export function delegationMaxOf(value: number | string | null): number {
  const n = Math.round(Number(value));
  return Number.isFinite(n) && String(value ?? '').trim() !== ''
    ? Math.min(MAX_DELEGATIONS_PER_DELEGATE, Math.max(1, n))
    : DEFAULT_DELEGATIONS_PER_DELEGATE;
}

/** The form state of a gremium. */
export interface GremiumForm {
  readonly name: string;
  /** Id of the chosen CD variant. `''` = none, which sends `null`. */
  readonly cdVariantId: string;
  readonly defaultLang: string;
  readonly allowVoteDelegation: boolean;
  /** Lead time in minutes before the meeting start for non-pool delegations. */
  readonly delegationLeadMinutes: number;
  /** Allow a delegation to a person outside the gremium and the pool. */
  readonly delegationAllowExternal: boolean;
  /** The most delegations that one person holds in one meeting. */
  readonly delegationMaxPerDelegate: number;
  /** An election takes the ballot of a delegation. */
  readonly delegationInElections: boolean;
  /** Default quorum in percent of the eligible voters. `null` = no quorum. */
  readonly quorumPercent: number | null;
  /** The least number of present persons for the quorum. `null` = no least number. */
  readonly quorumMinPresent: number | null;
  /** The quorum of a Wiederholungssitzung in percent. `null` = the normal quorum. */
  readonly repeatQuorumPercent: number | null;
  /** Guests of a public meeting can get a ballot. Counts only without a quorum. */
  readonly guestsMayVote: boolean;
  /** The month in which a term starts. `null`: a new Gremium takes the setting (§ 000948). */
  readonly termStartMonth: number | null;
  /** Extra protocol recipients, one address per line. */
  readonly mailRecipients: string;
  /** The final protocols show on the public protocol page. */
  readonly protocolsPublic: boolean;
}

export function emptyGremiumForm(): GremiumForm {
  return {
    name: '',
    cdVariantId: '',
    defaultLang: 'de',
    allowVoteDelegation: false,
    delegationLeadMinutes: 0,
    delegationAllowExternal: false,
    delegationMaxPerDelegate: DEFAULT_DELEGATIONS_PER_DELEGATE,
    delegationInElections: false,
    quorumPercent: null,
    quorumMinPresent: null,
    repeatQuorumPercent: null,
    guestsMayVote: false,
    termStartMonth: null,
    mailRecipients: '',
    protocolsPublic: false,
  };
}

/** A percent field: empty or invalid gives `null`, else a whole percent from 0 to 100. */
export function percentOrNull(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const n = Math.round(Number(value));
  return Number.isFinite(n) ? Math.min(100, Math.max(0, n)) : null;
}

/** Split the recipient text into addresses. A newline, a comma or a semicolon separates. */
export function parseRecipients(raw: string): readonly string[] {
  return raw
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * The dialog that creates or edits a gremium.
 *
 * It holds every setting of a gremium (gaps N38): name (the slug comes from the name of
 * a new gremium and never changes after), CD variant, default language, quorum, the
 * quorum of a Wiederholungssitzung, the guest ballot (it counts only without a quorum,
 * so a quorum locks the switch), vote delegation with its lead time and the delegation to external persons, and the extra
 * protocol recipients (`PUT /admin/committees/{id}/mail-recipients`, after the base data).
 * If the dialog cannot read the recipients, the field stays locked and a save sends only
 * the base data: the PUT replaces the list, so an empty field would delete it.
 * There is no switch for changing a ballot after casting: a ballot never changes.
 *
 * The switch "Öffentlich" puts the final protocols on the public protocol page. Turning
 * it on for a gremium that has it off asks first ("Protokolle veröffentlichen?", in the
 * same dialog): it names how many final protocols become readable without a login and
 * how many still need their public version, which a job of the server makes.
 */
import { LoadStateComponent, loadStateOf } from '@shared/ui/load-state/load-state.component';

@Component({
  selector: 'app-gremium-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LoadStateComponent,
    NoteComponent,
    SkeletonComponent,
    FormsModule,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    SelectFieldComponent,
    SwitchComponent,
  ],
  templateUrl: './gremium-dialog.component.html',
  styleUrl: './gremium-dialog.component.scss',
})
export class GremiumDialogComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input(false);
  /** The gremium to edit. `null` creates a new gremium. */
  readonly gremium = input<Gremium | null>(null);
  /** The CD variants for the dropdown (`GET /cd-variants`). */
  readonly cdVariants = input<readonly CdVariantOption[]>([]);

  readonly closed = output<void>();
  /** The saved gremium, after the base data and the recipients. */
  /** `recipients` is `null` when the dialog did not save them (their read failed). */
  readonly saved = output<{ gremium: Gremium; created: boolean; recipients: string[] | null }>();
  /**
   * The server saved the base data, but the PUT of the recipients failed and the dialog
   * stays open. The page reloads its list, so a cancel does not lose the saved change.
   */
  readonly baseSaved = output<{ gremium: Gremium; created: boolean }>();

  protected readonly form = signal<GremiumForm>(emptyGremiumForm());
  protected readonly saving = signal(false);
  /** The error of the last save, shown above the footer. */
  protected readonly error = signal('');
  /** The recipients load after the opening; the field waits for them. */
  protected readonly recipientsLoading = signal(false);
  /** The read of the recipients failed. The field stays locked and a save keeps them. */
  protected readonly recipientsLoadFailed = signal(false);
  /** The recipient field is locked while it loads or after its read failed. */
  protected readonly recipientsLocked = computed(
    () => this.recipientsLoading() || this.recipientsLoadFailed(),
  );
  /**
   * A new gremium that the server created while its recipients failed. A second save
   * then changes this gremium and does not create another one.
   */
  private created: Gremium | null = null;

  /** The question before the switch to "public" is saved. */
  protected readonly confirmPublic = signal(false);
  /** The counts of the question; `null` while they load or when the read failed. */
  protected readonly preview = signal<GremiumPublicPreview | null>(null);
  protected readonly previewLoading = signal(false);
  /** The read of the counts failed: the question shows without them. */
  protected readonly previewFailed = signal(false);
  protected readonly previewState = loadStateOf(this.previewLoading, this.previewFailed);

  /** The implications of a public gremium ("Was das bedeutet"). */
  protected readonly implications = [
    { icon: 'check', key: 'admin.gremien.publicImplies.final' },
    { icon: 'file', key: 'admin.gremien.publicImplies.version' },
    { icon: 'lock', key: 'admin.gremien.publicImplies.nonPublic' },
    { icon: 'history', key: 'admin.gremien.publicImplies.retro' },
    { icon: 'cal', key: 'admin.gremien.publicImplies.meetings' },
  ] as const;

  protected readonly isNew = computed(() => this.gremium() === null);
  protected readonly slug = computed(
    () => this.gremium()?.slug ?? (slugify(this.form().name) || '—'),
  );
  protected readonly cdOptions = computed<SelectOption[]>(() =>
    this.cdVariants().map((v) => ({ value: v.id, label: v.name })),
  );
  protected readonly langOptions = computed<SelectOption[]>(() =>
    this.i18n.locales().map((code) => ({ value: code, label: this.i18n.languageName(code) })),
  );
  /** The twelve months by name, for the start of the term. */
  protected readonly monthOptions = computed<SelectOption[]>(() => {
    const name = new Intl.DateTimeFormat(this.i18n.formatLocale(), { month: 'long', timeZone: 'UTC' });
    return Array.from({ length: 12 }, (_, i) => ({
      value: String(i + 1),
      label: name.format(new Date(Date.UTC(2024, i, 1))),
    }));
  });
  protected readonly canSave = computed(() => !!this.form().name.trim() && !this.saving());

  constructor() {
    effect(() => {
      if (!this.open()) return;
      const g = this.gremium();
      untracked(() => this.reset(g));
    });
  }

  private reset(g: Gremium | null): void {
    this.created = null;
    this.confirmPublic.set(false);
    this.preview.set(null);
    this.previewLoading.set(false);
    this.previewFailed.set(false);
    this.error.set('');
    this.saving.set(false);
    this.recipientsLoadFailed.set(false);
    if (!g) {
      this.form.set(emptyGremiumForm());
      this.recipientsLoading.set(false);
      this.loadDefaults();
      return;
    }
    this.form.set({
      name: g.name,
      cdVariantId: g.cdVariantId ?? '',
      defaultLang: g.defaultLang,
      allowVoteDelegation: g.allowVoteDelegation,
      delegationLeadMinutes: g.delegationLeadMinutes ?? 0,
      delegationAllowExternal: g.delegationAllowExternal ?? false,
      delegationMaxPerDelegate: g.delegationMaxPerDelegate ?? DEFAULT_DELEGATIONS_PER_DELEGATE,
      delegationInElections: g.delegationInElections ?? false,
      quorumPercent: g.quorumPercent ?? null,
      quorumMinPresent: g.quorumMinPresent ?? null,
      repeatQuorumPercent: g.repeatQuorumPercent ?? null,
      guestsMayVote: g.guestsMayVote ?? false,
      termStartMonth: g.termStartMonth ?? null,
      mailRecipients: '',
      protocolsPublic: g.protocolsPublic ?? false,
    });
    this.recipientsLoading.set(true);
    this.api.getGremiumMailRecipients(g.id).subscribe({
      next: ({ recipients }) => {
        this.recipientsLoading.set(false);
        this.form.update((f) => ({ ...f, mailRecipients: recipients.join('\n') }));
      },
      error: () => {
        this.recipientsLoading.set(false);
        this.recipientsLoadFailed.set(true);
        this.error.set(this.i18n.translate('admin.gremien.recipientsLoadFailedKept'));
      },
    });
  }

  /**
   * A new Gremium starts with the defaults of the meeting settings (§ 000906). A field
   * that the admin changed before the answer stays.
   */
  private loadDefaults(): void {
    const empty = emptyGremiumForm();
    this.api.getGremiumDefaults().subscribe({
      next: (d) => {
        if (!this.open() || this.gremium() !== null) return;
        this.form.update((f) => ({
          ...f,
          ...(f.quorumPercent === empty.quorumPercent ? { quorumPercent: d.quorumPercent } : {}),
          ...(f.repeatQuorumPercent === empty.repeatQuorumPercent
            ? { repeatQuorumPercent: d.repeatQuorumPercent }
            : {}),
          ...(f.guestsMayVote === empty.guestsMayVote ? { guestsMayVote: d.guestsMayVote } : {}),
          ...(f.allowVoteDelegation === empty.allowVoteDelegation
            ? { allowVoteDelegation: d.allowVoteDelegation }
            : {}),
          ...(f.delegationLeadMinutes === empty.delegationLeadMinutes
            ? { delegationLeadMinutes: d.delegationLeadMinutes }
            : {}),
          ...(f.delegationMaxPerDelegate === empty.delegationMaxPerDelegate
            ? { delegationMaxPerDelegate: d.delegationMaxPerDelegate }
            : {}),
        }));
      },
      error: () => {},
    });
  }

  protected patch<K extends keyof GremiumForm>(key: K, value: GremiumForm[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  /** Lead time: empty or invalid gives 0, else whole minutes from 0 to 30 days. */
  protected patchLead(value: number | string | null): void {
    const n = Math.round(Number(value));
    this.patch(
      'delegationLeadMinutes',
      Number.isFinite(n) ? Math.min(MAX_DELEGATION_LEAD_MINUTES, Math.max(0, n)) : 0,
    );
  }

  protected patchMax(value: number | string | null): void {
    this.patch('delegationMaxPerDelegate', delegationMaxOf(value));
  }

  /** Least number of present persons: empty gives `null`, else a whole number from 1. */
  protected patchMinPresent(value: number | string | null): void {
    if (value === null || value === undefined || String(value).trim() === '') {
      this.patch('quorumMinPresent', null);
      return;
    }
    const n = Math.round(Number(value));
    this.patch('quorumMinPresent', Number.isFinite(n) ? Math.min(1000, Math.max(1, n)) : null);
  }

  /** Quorum: empty gives `null` (no quorum), else a whole percent from 0 to 100. */
  protected patchQuorum(
    value: number | string | null,
    key: 'quorumPercent' | 'repeatQuorumPercent' = 'quorumPercent',
  ): void {
    this.patch(key, percentOrNull(value));
  }

  protected close(): void {
    this.closed.emit();
  }

  /** "Abbrechen" in the question: back to the form, nothing saved. */
  protected backFromConfirm(): void {
    this.confirmPublic.set(false);
  }

  /**
   * Save. Turning "public" on for a stored gremium asks first: the question loads the
   * counts of the protocols that the switch publishes.
   */
  protected submit(): void {
    if (!this.canSave() || this.recipientsLoading()) return;
    const g = this.gremium();
    if (g && this.form().protocolsPublic && !g.protocolsPublic && !this.confirmPublic()) {
      this.confirmPublic.set(true);
      this.loadPreview();
      return;
    }
    this.save();
  }

  /** Read the counts of the question; also the retry of the load error (§ 000576). */
  protected loadPreview(): void {
    const g = this.gremium();
    if (!g) return;
    this.preview.set(null);
    this.previewFailed.set(false);
    this.previewLoading.set(true);
    this.api.getGremiumPublicPreview(g.id).subscribe({
      next: (p) => {
        this.previewLoading.set(false);
        this.preview.set(p);
      },
      error: () => {
        this.previewFailed.set(true);
        this.previewLoading.set(false);
      },
    });
  }

  /** "Veröffentlichen" in the question. */
  protected confirmAndSave(): void {
    this.confirmPublic.set(false);
    this.save();
  }

  protected patchTermStart(value: string): void {
    const month = Number(value);
    if (Number.isInteger(month) && month >= 1 && month <= 12) this.patch('termStartMonth', month);
  }

  /**
   * The recipients are not saved when their stored list failed to load, because the PUT would
   * replace it with the empty field.
   */
  private save(): void {
    const f = this.form();
    this.saving.set(true);
    this.error.set('');
    const base = {
      name: f.name.trim(),
      cdVariantId: f.cdVariantId || null,
      defaultLang: f.defaultLang,
      allowVoteDelegation: f.allowVoteDelegation,
      delegationLeadMinutes: f.delegationLeadMinutes,
      delegationAllowExternal: f.delegationAllowExternal,
      delegationMaxPerDelegate: f.delegationMaxPerDelegate,
      delegationInElections: f.delegationInElections,
      quorumPercent: f.quorumPercent,
      quorumMinPresent: f.quorumMinPresent,
      repeatQuorumPercent: f.repeatQuorumPercent,
      guestsMayVote: f.guestsMayVote,
      ...(f.termStartMonth === null ? {} : { termStartMonth: f.termStartMonth }),
      protocolsPublic: f.protocolsPublic,
    } satisfies GremiumUpdateBody;
    const isNew = this.isNew();
    const g = this.gremium() ?? this.created;
    const createBody: GremiumCreateBody = {
      ...base,
      slug: slugify(f.name) || base.name.toLowerCase(),
    };
    const req = g ? this.api.updateGremium(g.id, base) : this.api.createGremium(createBody);
    req.subscribe({
      next: (saved) => {
        if (isNew) this.created = saved;
        if (this.recipientsLoadFailed()) {
          this.saving.set(false);
          this.saved.emit({ gremium: saved, created: isNew, recipients: null });
          return;
        }
        this.saveRecipients(saved, isNew);
      },
      error: (err: { status?: number }) =>
        this.fail(err.status === 409 ? 'admin.gremien.slugTaken' : 'admin.gremien.toast.failed'),
    });
  }

  /** Save the extra protocol recipients after the base data. */
  private saveRecipients(saved: Gremium, created: boolean): void {
    const recipients = parseRecipients(this.form().mailRecipients);
    this.api.setGremiumMailRecipients(saved.id as Uuid, recipients).subscribe({
      next: (r) => {
        this.saving.set(false);
        this.saved.emit({ gremium: saved, created, recipients: r.recipients });
      },
      error: (err: { status?: number }) => {
        this.fail(
          err.status === 422 ? 'admin.gremien.recipientsInvalid' : 'admin.gremien.recipientsFailed',
        );
        this.baseSaved.emit({ gremium: saved, created });
      },
    });
  }

  private fail(
    key:
      | 'admin.gremien.slugTaken'
      | 'admin.gremien.toast.failed'
      | 'admin.gremien.recipientsInvalid'
      | 'admin.gremien.recipientsFailed',
  ): void {
    this.saving.set(false);
    const text = this.i18n.translate(key);
    if (key === 'admin.gremien.toast.failed' || key === 'admin.gremien.recipientsFailed') {
      this.toast.error(text);
    } else {
      this.error.set(text);
    }
  }
}
