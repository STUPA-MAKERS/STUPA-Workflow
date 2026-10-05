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
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  InputComponent,
  SelectComponent,
  type SelectOption,
  SwitchComponent,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import {
  type CdVariantOption,
  type Gremium,
  type GremiumCreateBody,
  type GremiumUpdateBody,
  slugify,
} from '../../admin.models';

/** The largest lead time in minutes that the server accepts (30 days). */
export const MAX_DELEGATION_LEAD_MINUTES = 60 * 24 * 30;

/** The form state of a gremium. */
export interface GremiumForm {
  name: string;
  /** Id of the chosen CD variant. `''` = none, which sends `null`. */
  cdVariantId: string;
  defaultLang: string;
  allowVoteDelegation: boolean;
  /** Lead time in minutes before the meeting start for non-pool delegations. */
  delegationLeadMinutes: number;
  /** Allow a delegation to a person outside the gremium and the pool. */
  delegationAllowExternal: boolean;
  /** Default quorum in percent of the eligible voters. `null` = no quorum. */
  quorumPercent: number | null;
  /** Extra protocol recipients, one address per line. */
  mailRecipients: string;
}

export function emptyGremiumForm(): GremiumForm {
  return {
    name: '',
    cdVariantId: '',
    defaultLang: 'de',
    allowVoteDelegation: false,
    delegationLeadMinutes: 0,
    delegationAllowExternal: false,
    quorumPercent: null,
    mailRecipients: '',
  };
}

/** Split the recipient text into addresses. A newline, a comma or a semicolon separates. */
export function parseRecipients(raw: string): string[] {
  return raw
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * The dialog that creates or edits a gremium (board Verwaltung-Gremium-Dialog).
 *
 * It holds every setting of a gremium (gaps N38): name (the slug comes from the name of
 * a new gremium and never changes after), CD variant, default language, quorum, vote
 * delegation with its lead time and the delegation to external persons, and the extra
 * protocol recipients (`PUT /admin/gremien/{id}/mail-recipients`, after the base data).
 * If the dialog cannot read the recipients, the field stays locked and a save sends only
 * the base data: the PUT replaces the list, so an empty field would delete it.
 * There is no switch for changing a ballot after casting: a ballot never changes (O11).
 */
@Component({
  selector: 'app-gremium-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    InputComponent,
    SelectComponent,
    SwitchComponent,
  ],
  templateUrl: './gremium-dialog.component.html',
  styleUrl: './gremium-dialog.component.scss',
})
export class GremiumDialogComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);

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

  protected readonly isNew = computed(() => this.gremium() === null);
  protected readonly slug = computed(
    () => this.gremium()?.slug ?? (slugify(this.form().name) || '—'),
  );
  protected readonly cdOptions = computed<SelectOption[]>(() =>
    this.cdVariants().map((v) => ({ value: v.id, label: v.name })),
  );
  protected readonly langOptions = computed<SelectOption[]>(() => [
    { value: 'de', label: this.i18n.translate('admin.gremien.langDe') },
    { value: 'en', label: this.i18n.translate('admin.gremien.langEn') },
  ]);
  protected readonly canSave = computed(() => !!this.form().name.trim() && !this.saving());

  constructor() {
    // Each opening starts from the gremium (or an empty form), never from the last edit.
    effect(() => {
      if (!this.open()) return;
      const g = this.gremium();
      untracked(() => this.reset(g));
    });
  }

  private reset(g: Gremium | null): void {
    this.created = null;
    this.error.set('');
    this.saving.set(false);
    this.recipientsLoadFailed.set(false);
    if (!g) {
      this.form.set(emptyGremiumForm());
      this.recipientsLoading.set(false);
      return;
    }
    this.form.set({
      name: g.name,
      cdVariantId: g.cdVariantId ?? '',
      defaultLang: g.defaultLang,
      allowVoteDelegation: g.allowVoteDelegation,
      delegationLeadMinutes: g.delegationLeadMinutes ?? 0,
      delegationAllowExternal: g.delegationAllowExternal ?? false,
      quorumPercent: g.quorumPercent ?? null,
      mailRecipients: '',
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

  /** Quorum: empty gives `null` (no quorum), else a whole percent from 0 to 100. */
  protected patchQuorum(value: number | string | null): void {
    if (value === null || value === undefined || String(value).trim() === '') {
      this.patch('quorumPercent', null);
      return;
    }
    const n = Math.round(Number(value));
    this.patch('quorumPercent', Number.isFinite(n) ? Math.min(100, Math.max(0, n)) : null);
  }

  protected close(): void {
    this.closed.emit();
  }

  protected submit(): void {
    const f = this.form();
    if (!this.canSave() || this.recipientsLoading()) return;
    this.saving.set(true);
    this.error.set('');
    const base = {
      name: f.name.trim(),
      cdVariantId: f.cdVariantId || null,
      defaultLang: f.defaultLang,
      allowVoteDelegation: f.allowVoteDelegation,
      delegationLeadMinutes: f.delegationLeadMinutes,
      delegationAllowExternal: f.delegationAllowExternal,
      quorumPercent: f.quorumPercent,
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
        // Without the stored list, the PUT would replace it with the empty field.
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
      // The base data is saved. Only the recipients failed, mostly an invalid address.
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
    this.error.set(this.i18n.translate(key));
  }
}
