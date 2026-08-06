import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  Application,
  ApplicationComment,
  ApplicationState,
  ApplicationVersion,
  CommentVisibility,
  FormFieldDef,
  Transition,
  Uuid,
} from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import { toFormlyFields } from '@shared/forms/formly-mapper';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { SelectComponent, type SelectOption } from '@stupa-makers/ui-kit';
import { CardComponent } from '@stupa-makers/ui-kit';
import { DialogComponent } from '@stupa-makers/ui-kit';
import { IconComponent } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import {
  BudgetTreeApi,
  type BudgetTreeNode,
  type FiscalYear,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { AttachmentsPanelComponent } from './attachments-panel.component';
import { applicationTitle, formatFieldValue } from './applications.util';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';

/** Comparison offer / cost position for the structured detail view. */
interface DetailOffer {
  label?: string;
  value?: number | null;
  preferred?: boolean;
}
interface DetailPosition {
  label: string;
  offers: DetailOffer[];
  /** Opt-out of comparison offers (with the applicant's reason). */
  noOffers?: boolean;
  noOffersReason?: string;
}

/**
 * Application detail: fields, version history with diff, comments, and status actions.
 *
 * A comment is internal or public. A status action asks for a confirmation and handles a
 * 409 answer. RBAC here only gates the UX. The server decides. The actions and the
 * internal comment visibility appear only with `application.manage`.
 */
@Component({
  selector: 'app-applications-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageHeaderComponent,
    FormsModule,
    FormlyForm,
    LocalizedDatePipe,
    TranslatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    DialogComponent,
    IconComponent,
    SelectComponent,
    CostCentreTreeComponent,
    AttachmentsPanelComponent,
    MarkdownViewComponent,
  ],
  templateUrl: './applications-detail.component.html',
  styleUrl: './applications-detail.component.scss',
})
export class ApplicationsDetailComponent {
  private readonly api = inject(ApiClient);
  private readonly budgetApi = inject(BudgetTreeApi);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);

  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly error = signal(false);

  readonly app = signal<Application | null>(null);
  readonly versions = signal<ApplicationVersion[]>([]);
  readonly comments = signal<ApplicationComment[]>([]);
  /** Field definitions of the effective form for labels and typed values. Empty on error. */
  readonly formFields = signal<FormFieldDef[]>([]);

  readonly newComment = signal('');
  readonly visibility = signal<CommentVisibility>('public');
  readonly posting = signal(false);

  /** The version history starts collapsed. The card header holds the toggle. */
  readonly historyOpen = signal(false);

  /** Manual transitions that the server guard allows, plus the fire in flight. */
  readonly transitions = signal<Transition[]>([]);
  readonly firing = signal<Uuid | null>(null);
  readonly canTransition = computed(() => this.auth.can('application.transition'));

  protected readonly budgetTree = signal<BudgetTreeNode[]>([]);
  protected readonly budgetChoice = signal('');
  protected readonly assigningBudget = signal(false);
  protected readonly budgetDialogOpen = signal(false);
  /** Fiscal-year choice among the years of the top budget of the selected cost centre.
   *  An empty value means automatic. The server then derives the single active year,
   *  or it answers 422. */
  protected readonly fiscalYears = signal<FiscalYear[]>([]);
  protected readonly fiscalChoice = signal('');
  /** Maps `budgetId` to "FULL-PATH – name" for the badge of the current cost centre. */
  private readonly budgetLabels = computed(
    () => new Map(flattenBudgetOptions(this.budgetTree()).map((o) => [o.value, o.label])),
  );
  protected budgetLabel(id: string | null | undefined): string {
    return (id && this.budgetLabels().get(id)) || '';
  }
  /** Maps `fiscalYearId` to the display text of a loaded fiscal year, for example `2026`. */
  private readonly fiscalLabels = computed(
    () => new Map(this.fiscalYears().map((y) => [y.id, y.display])),
  );
  protected fiscalLabel(id: string | null | undefined): string {
    return (id && this.fiscalLabels().get(id)) || '';
  }
  /** Dropdown options: "automatic" plus every fiscal year of the top budget.
   *  An inactive year carries a mark. */
  protected readonly fiscalOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('applications.budget.fiscalAuto') },
    ...this.fiscalYears().map((y) => ({
      value: y.id,
      label: y.active
        ? y.display
        : `${y.display} (${this.i18n.translate('applications.budget.fiscalInactive')})`,
    })),
  ]);
  /** Find the top budget (root) whose subtree contains the cost centre. */
  private topLevelIdOf(budgetId: string): string | null {
    const contains = (n: BudgetTreeNode): boolean =>
      n.id === budgetId || (n.children?.some(contains) ?? false);
    for (const root of this.budgetTree()) if (contains(root)) return root.id;
    return null;
  }
  /** Load the fiscal years of the selected cost centre's top budget (dropdown + badge). */
  private loadFiscalYears(budgetId: string | null): void {
    const top = budgetId ? this.topLevelIdOf(budgetId) : null;
    if (!top) {
      this.fiscalYears.set([]);
      return;
    }
    const seq = this.loadSeq;
    this.budgetApi.listFiscalYears(top).subscribe({
      next: (ys) => {
        if (seq === this.loadSeq) this.fiscalYears.set(ys);
      },
      error: () => {
        if (seq === this.loadSeq) this.fiscalYears.set([]);
      },
    });
  }
  /** Handle a cost centre picked in the dialog and reload the fiscal-year list.
   *  The fiscal-year choice survives only when the user picks the original cost
   *  centre again. */
  protected onBudgetPicked(id: string): void {
    this.budgetChoice.set(id);
    this.fiscalChoice.set(
      id === (this.app()?.budgetId ?? '') ? (this.app()?.fiscalYearId ?? '') : '',
    );
    this.loadFiscalYears(id || null);
  }
  protected openBudgetDialog(): void {
    const cur = this.app()?.budgetId ?? '';
    this.budgetChoice.set(cur);
    this.fiscalChoice.set(this.app()?.fiscalYearId ?? '');
    this.loadFiscalYears(cur || null);
    this.budgetDialogOpen.set(true);
  }

  // Inline editing for the creator or a manager, plus delete.
  readonly editing = signal(false);
  readonly editFields = signal<FormlyFieldConfig[]>([]);
  readonly savingEdit = signal(false);
  editForm = new FormGroup({});
  editModel: Record<string, unknown> = {};
  readonly confirmDelete = signal(false);
  readonly deleting = signal(false);
  readonly confirmErase = signal(false);
  readonly requestingErasure = signal(false);

  // Force status is a privileged override that needs `application.force_status`.
  // The dialog lazy-loads the flow states of the application. It asks for a target
  // state and for a mandatory reason.
  readonly canForceStatus = computed(() => this.auth.can('application.force_status'));
  readonly forceDialogOpen = signal(false);
  readonly forcingStatus = signal(false);
  private readonly forceStates = signal<ApplicationState[]>([]);
  readonly forceStateChoice = signal('');
  readonly forceNote = signal('');
  /** Target-state options: every state of the flow except the current one. */
  readonly forceStateOptions = computed<SelectOption[]>(() => {
    const currentId = this.app()?.state?.id ?? '';
    return this.forceStates()
      .filter((s) => s.id !== currentId)
      .map((s) => ({ value: s.id, label: s.label || s.key }));
  });

  private readonly router = inject(Router);
  readonly canManage = computed(() => this.auth.can('application.manage'));
  /**
   * Delete is irreversible and needs `application.delete` (#g9). An admin holds it
   * through the role bypass. Any other role holds it through an explicit grant. The
   * server gates on the same key.
   */
  readonly canDelete = computed(() => this.auth.can('application.delete'));
  readonly fmt = formatFieldValue;

  private id: Uuid = '';

  readonly title = computed(() =>
    applicationTitle(this.app()?.data, this.i18n.translate('applications.list.untitled')),
  );

  constructor() {
    // Use `paramMap`, not `snapshot`. Angular reuses the component on a
    // detail-to-detail navigation, so the constructor does not run again. A snapshot
    // would keep the old `id`. The subscription reloads on every `id` change.
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.loadApplication(pm.get('id') ?? '');
    });
  }

  /** Load sequence number that guards against a late response.
   *  A fast switch between detail pages can deliver a response of an earlier
   *  application. Such a response must not overwrite the current one. Each response
   *  checks that it still belongs to the latest load. */
  private loadSeq = 0;

  private loadApplication(id: Uuid): void {
    this.id = id;
    const seq = ++this.loadSeq;
    // Reset state for the (possibly new) id so nothing stale flashes through.
    this.app.set(null);
    this.versions.set([]);
    this.comments.set([]);
    this.formFields.set([]);
    this.newComment.set('');
    this.visibility.set('public');
    this.editing.set(false);
    this.confirmDelete.set(false);
    this.notFound.set(false);
    this.error.set(false);

    if (!id) {
      this.notFound.set(true);
      this.loading.set(false);
      return;
    }
    this.loading.set(true);
    this.api.getApplication(id, { quiet: true }).subscribe({
      next: (app) => {
        if (seq !== this.loadSeq) return;
        this.app.set(app);
        this.loading.set(false);
        this.loadAux();
        // Take the effective form from the pinned version of the application, not from
        // the active one. The labels and the edit fields then match the data that the
        // server validates.
        this.api.applicationForm(app.id).subscribe({
          next: (eff) => {
            if (seq === this.loadSeq) this.formFields.set(eff.sections.flatMap((s) => s.fields));
          },
          error: () => {
            if (seq === this.loadSeq) this.formFields.set([]);
          },
        });
      },
      error: (err: { status?: number }) => {
        if (seq !== this.loadSeq) return;
        this.loading.set(false);
        if (err.status === 404) this.notFound.set(true);
        else this.error.set(true);
      },
    });
  }

  /** Load the versions, the comments and the available transitions.
   *  An error degrades silently to an empty result. The transitions load only with
   *  the needed permission. The server filters them again. */
  private loadAux(): void {
    const seq = this.loadSeq;
    this.api.versions(this.id).subscribe({
      next: (v) => {
        if (seq === this.loadSeq) this.versions.set(v);
      },
      error: () => {},
    });
    this.api.comments(this.id, { quiet: true }).subscribe({
      next: (c) => {
        if (seq === this.loadSeq) this.comments.set(c);
      },
      error: () => {},
    });
    if (this.canTransition()) {
      this.api.transitions(this.id).subscribe({
        next: (t) => {
          if (seq === this.loadSeq) this.transitions.set(t);
        },
        error: () => {
          if (seq === this.loadSeq) this.transitions.set([]);
        },
      });
    }
    // The badge label and the dialog picker both need the cost-centre tree.
    if (this.canManage()) {
      this.budgetChoice.set(this.app()?.budgetId ?? '');
      this.fiscalChoice.set(this.app()?.fiscalYearId ?? '');
      this.budgetApi.tree().subscribe({
        next: (tree) => {
          if (seq !== this.loadSeq) return;
          this.budgetTree.set(tree);
          // The badge needs the fiscal years of the current cost centre.
          this.loadFiscalYears(this.app()?.budgetId ?? null);
        },
        error: () => {
          if (seq === this.loadSeq) this.budgetTree.set([]);
        },
      });
    }
  }

  /** Assign or unassign the cost centre with POST /assign-budget, then reload. */
  assignBudget(): void {
    if (this.assigningBudget()) return;
    this.assigningBudget.set(true);
    this.budgetApi
      .assignBudget(this.id, this.budgetChoice() || null, this.fiscalChoice() || null)
      .subscribe({
        next: () => {
          this.assigningBudget.set(false);
          this.budgetDialogOpen.set(false);
          this.toast.success(this.i18n.translate('applications.actions.success'));
          this.refresh();
        },
        error: (err: { status?: number }) => {
          this.assigningBudget.set(false);
          const key =
            err.status === 422
              ? 'applications.budget.invalid'
              : err.status === 403
                ? 'applications.transitions.forbidden'
                : 'applications.actions.error';
          this.toast.error(this.i18n.translate(key));
        },
      });
  }

  /** Build the application data as label and value rows.
   *  A field definition gives the label and the typed value. An unknown key stays
   *  raw. The rows omit `title`, because the header shows it, and they omit the pure
   *  display fields. A long text (`textarea`) carries the `md` flag and renders as
   *  Markdown. This keeps the newlines and the simple formatting. */
  dataEntries(app: Application): { key: string; label: string; value: string; md: boolean }[] {
    const lang = this.i18n.locale();
    const byKey = new Map(this.formFields().map((f) => [f.key, f]));
    const rows: { key: string; label: string; value: string; md: boolean }[] = [];
    const seen = new Set<string>();

    const pushField = (f: FormFieldDef): void => {
      if (f.type === 'markdown' || f.type === 'computed') return;
      // Cost positions get their own block with the positions and the offers.
      if (f.type === 'positions') return;
      if (f.key === 'title') return;
      if (!(f.key in app.data)) return;
      seen.add(f.key);
      rows.push({
        key: f.key,
        label: resolveI18n(f.label, lang),
        value: this.formatByField(f, app.data[f.key]),
        md: f.type === 'textarea',
      });
    };

    for (const f of this.formFields()) pushField(f);
    // Show data without a matching field definition as a raw value. Skip `title`.
    for (const [key, value] of Object.entries(app.data)) {
      if (seen.has(key) || key === 'title' || byKey.has(key)) continue;
      rows.push({ key, label: key, value: formatFieldValue(value), md: false });
    }
    return rows;
  }

  /** Format a value for display based on its field type. */
  private formatByField(field: FormFieldDef, value: unknown): string {
    if (value === null || value === undefined || value === '') return '—';
    const lang = this.i18n.locale();
    if (field.type === 'positions') return this.formatPositions(value);
    if (field.type === 'checkbox' && typeof value === 'boolean') {
      return this.i18n.translate(value ? 'common.yes' : 'common.no');
    }
    // A dynamic picker for a Gremium or a budget carries the options of the server in
    // the effective form. Resolve them to names, like a plain select.
    if (field.type === 'select' || field.type === 'gremium_select' || field.type === 'budget_select') {
      const opt = field.options?.find((o) => o.value === value);
      return opt ? resolveI18n(opt.label, lang) : formatFieldValue(value);
    }
    if (field.type === 'multiselect' && Array.isArray(value)) {
      return value
        .map((v) => {
          const opt = field.options?.find((o) => o.value === v);
          return opt ? resolveI18n(opt.label, lang) : String(v);
        })
        .join(', ');
    }
    if (field.type === 'currency') {
      const n = Number(value);
      if (Number.isFinite(n)) {
        return new Intl.NumberFormat(lang, { style: 'currency', currency: 'EUR' }).format(n);
      }
    }
    return formatFieldValue(value);
  }

  /** Build the cost-position fields as a structured block for the detail view.
   *  Each position carries its comparison offers, the preferred one included. */
  positionEntries(app: Application): {
    key: string;
    label: string;
    positions: DetailPosition[];
  }[] {
    const lang = this.i18n.locale();
    const out: { key: string; label: string; positions: DetailPosition[] }[] = [];
    for (const f of this.formFields()) {
      if (f.type !== 'positions' || !(f.key in app.data)) continue;
      const raw = app.data[f.key];
      if (!Array.isArray(raw)) continue;
      const positions = (raw as DetailPosition[]).map((p) => ({
        label: p.label ?? '',
        offers: Array.isArray(p.offers) ? p.offers : [],
        noOffers: p.noOffers === true,
        noOffersReason: typeof p.noOffersReason === 'string' ? p.noOffersReason : '',
      }));
      out.push({ key: f.key, label: resolveI18n(f.label, lang), positions });
    }
    return out;
  }

  /** Value of a comparison offer / position as currency. */
  money(value: number | null | undefined): string {
    const n = Number(value ?? 0);
    return new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: 'EUR',
    }).format(Number.isFinite(n) ? n : 0);
  }

  /** The value of a position is the value of the preferred offer. */
  positionValue(p: DetailPosition): number {
    return p.offers.find((o) => o.preferred)?.value ?? 0;
  }

  /** Sum over all position values. */
  positionsTotal(positions: DetailPosition[]): number {
    return positions.reduce((s, p) => s + this.positionValue(p), 0);
  }

  /** Format the cost positions compactly: the position count and the preferred sum. */
  private formatPositions(value: unknown): string {
    if (!Array.isArray(value)) return '—';
    let total = 0;
    for (const p of value as { offers?: { value?: number | null; preferred?: boolean }[] }[]) {
      const pref = (p.offers ?? []).find((o) => o.preferred);
      total += pref?.value ?? 0;
    }
    const sum = new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: 'EUR',
    }).format(total);
    return `${value.length} × ${this.i18n.translate('applications.detail.positionsTotal')}: ${sum}`;
  }


  amount(app: Application): string {
    if (app.amount === null) return this.i18n.translate('applications.detail.notProvided');
    const value = Number(app.amount);
    if (Number.isNaN(value)) return app.amount;
    return new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: app.currency ?? 'EUR',
    }).format(value);
  }

  isEmptyDiff(version: ApplicationVersion): boolean {
    const d = version.diff;
    return !!d && !d.added.length && !d.removed.length && !d.changed.length;
  }

  startEdit(app: Application): void {
    const lang = this.i18n.locale();
    this.editFields.set(toFormlyFields(this.formFields(), lang, { has_budget: true }));
    this.editModel = structuredClone(app.data);
    this.editForm = new FormGroup({});
    this.editing.set(true);
  }

  cancelEdit(): void {
    this.editing.set(false);
  }

  saveEdit(): void {
    if (this.editForm.invalid || this.savingEdit()) return;
    this.savingEdit.set(true);
    this.api.updateApplication(this.id, { ...this.editModel }).subscribe({
      next: () => {
        this.savingEdit.set(false);
        this.editing.set(false);
        this.toast.success(this.i18n.translate('applications.detail.saved'));
        this.refresh();
      },
      error: (err: { status?: number }) => {
        this.savingEdit.set(false);
        const key =
          err.status === 409 ? 'applications.detail.locked' : 'applications.detail.saveFailed';
        this.toast.error(this.i18n.translate(key));
      },
    });
  }

  doDelete(): void {
    if (this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteApplication(this.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(false);
        this.toast.success(this.i18n.translate('applications.detail.deleted'));
        void this.router.navigate(['/applications']);
      },
      error: () => {
        this.deleting.set(false);
        this.toast.error(this.i18n.translate('applications.detail.deleteFailed'));
      },
    });
  }

  /** Request the erasure of the application data of the applicant, per GDPR Art. 17.
   *  The magic-link view offers this action. */
  doRequestErasure(): void {
    if (this.requestingErasure()) return;
    this.requestingErasure.set(true);
    this.api.requestErasure(this.id).subscribe({
      next: () => {
        this.requestingErasure.set(false);
        this.confirmErase.set(false);
        this.toast.success(this.i18n.translate('applications.detail.eraseRequested'));
      },
      error: () => {
        this.requestingErasure.set(false);
        this.toast.error(this.i18n.translate('applications.detail.eraseRequestFailed'));
      },
    });
  }

  /** Open the force-status dialog, lazy-load the flow states and reset the form. */
  openForceDialog(): void {
    this.forceStateChoice.set('');
    this.forceNote.set('');
    if (!this.forceStates().length) {
      const seq = this.loadSeq;
      this.api.flowStates(this.id).subscribe({
        next: (states) => {
          if (seq === this.loadSeq) this.forceStates.set(states);
        },
        error: () => {},
      });
    }
    this.forceDialogOpen.set(true);
  }

  /** Force the application directly into the chosen state. The reason is mandatory.
   *  The server bypasses the flow guards. A 403 or a 409 answer shows a toast. */
  doForceStatus(): void {
    const stateId = this.forceStateChoice();
    const note = this.forceNote().trim();
    if (!stateId || !note || this.forcingStatus()) return;
    this.forcingStatus.set(true);
    this.api.forceStatus(this.id, { stateId, note }).subscribe({
      next: () => {
        this.forcingStatus.set(false);
        this.forceDialogOpen.set(false);
        this.toast.success(this.i18n.translate('applications.actions.success'));
        this.refresh();
      },
      error: (err: { status?: number }) => {
        this.forcingStatus.set(false);
        const key =
          err.status === 403
            ? 'applications.transitions.forbidden'
            : err.status === 409
              ? 'applications.actions.conflict'
              : 'applications.actions.error';
        this.toast.error(this.i18n.translate(key));
      },
    });
  }

  /** Display name of a comment: the author, or a fallback based on the role. */
  protected authorName(comment: ApplicationComment): string {
    if (comment.author) return comment.author;
    return this.i18n.translate(
      comment.authorKind === 'applicant'
        ? 'applications.comments.author.applicant'
        : 'applications.comments.author.committee',
    );
  }

  /** Initial(s) for the chat avatar. */
  protected initial(name: string): string {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    const first = parts[0][0];
    const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
    return (first + last).toUpperCase();
  }

  /** Enter sends the comment. Shift+Enter makes a line break.
   *  The Angular `keydown.enter` binding matches the unmodified Enter only. */
  protected onComposerEnter(event: Event): void {
    this.submitComment(event);
  }

  submitComment(event: Event): void {
    event.preventDefault();
    const body = this.newComment().trim();
    if (!body || this.posting()) return;
    this.posting.set(true);
    this.api.addComment(this.id, body, this.visibility()).subscribe({
      next: (created) => {
        this.comments.update((list) => [...list, created]);
        this.newComment.set('');
        this.posting.set(false);
        this.toast.success(this.i18n.translate('applications.comments.added'));
      },
      error: () => {
        this.posting.set(false);
        this.toast.error(this.i18n.translate('applications.comments.error'));
      },
    });
  }

  /** Fire a manual transition with POST /transition, then reload the application.
   *  The server checks the guard again. A 403 or a 409 answer shows a toast and
   *  refreshes. */
  fire(t: Transition): void {
    if (this.firing() !== null) return;
    this.firing.set(t.id);
    this.api.fireTransition(this.id, { transitionId: t.id }).subscribe({
      next: () => {
        this.firing.set(null);
        this.toast.success(this.i18n.translate('applications.actions.success'));
        this.refresh();
      },
      error: (err: { status?: number }) => {
        this.firing.set(null);
        const key =
          err.status === 403
            ? 'applications.transitions.forbidden'
            : err.status === 409
              ? 'applications.actions.conflict'
              : 'applications.actions.error';
        this.toast.error(this.i18n.translate(key));
        this.refresh();
      },
    });
  }

  /** Reload the application and the dependent sections after a transition. */
  private refresh(): void {
    const seq = this.loadSeq;
    this.api.getApplication(this.id, { quiet: true }).subscribe({
      next: (app) => {
        if (seq !== this.loadSeq) return;
        this.app.set(app);
        this.loadAux();
      },
      error: () => {},
    });
  }
}
