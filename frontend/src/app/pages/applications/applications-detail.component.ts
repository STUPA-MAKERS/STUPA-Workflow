import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgTemplateOutlet } from '@angular/common';
import { FormGroup, FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  ActorInfo,
  Application,
  ApplicationComment,
  ApplicationType,
  ApplicationVersion,
  CommentVisibility,
  FormFieldDef,
  FormSection,
  ProblemDetail,
  TimelineEntry,
  Transition,
  Uuid,
} from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import { actorLabel } from '@shared/actor-label.util';
import { localToday } from './capture/application-capture.component';
import { toFormlySections } from '@shared/forms/formly-mapper';
import { formatAnswer, formatEuro, formatFieldValue } from '@shared/forms/answer-format';
import {
  normalizePositions,
  positionValue,
  positionsTotal,
} from '@shared/forms/positions';
import { applyServerErrors, clearServerErrors } from '@shared/forms/server-errors';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { AnswerViewComponent } from '@shared/forms/answer-view/answer-view.component';
import {
  AvatarComponent,
  EmptyStateComponent,
  FieldGroupComponent,
  FieldRowComponent,
  HistoryComponent,
  NoteComponent,
  RowMenuComponent,
  StatusTextComponent,
  flowColorKind,
  type HistoryChange,
  type HistoryEntry,
  type RowMenuItem,
  type RowMenuSection,
} from '@shared/ui';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  MEDIA,
  SegmentedComponent,
  SelectComponent,
  TabsComponent,
  ToastService,
  type SegmentedOption,
  type SelectOption,
  type TabItem,
} from '@stupa-makers/ui-kit';
import {
  BudgetTreeApi,
  type BudgetTreeNode,
  type FiscalYear,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import { AttachmentsPanelComponent } from './attachments-panel.component';
import { applicationTitle, transitionLooks } from './applications.util';
import { AgendaDialogComponent } from './agenda-dialog/agenda-dialog.component';
import { ApplicationsPageService } from './applications-page.service';
import { ForceStatusDialogComponent } from './force-status-dialog/force-status-dialog.component';
import { ShareLinksDialogComponent } from './share-links-dialog/share-links-dialog.component';
import { mediaQuerySignal } from '../../layout/media-query';
import { RailStatusService } from '../../layout/rail-status.service';
import { SheetBarComponent } from '@shared/ui/sheet-bar/sheet-bar.component';
import { provideFormly } from '@shared/formly/formly.providers';

/** Field types whose old and new value do not fit on one line of the history. The
 *  history opens them as blocks below the change ("Werte anzeigen"). */
const BLOCK_DIFF: ReadonlySet<string> = new Set(['positions', 'table', 'textarea']);

/** The tabs of the detail when the list and the detail do not sit side by side. */
type DetailTab = 'app' | 'history' | 'comments' | 'files';

/**
 * Application detail: the sheet beside the list (board Anträge), or alone with tabs on a
 * narrow screen (board Schmal-Anträge-Detail).
 *
 * Header: "<Typ> · Version n", the title, "status · gremium · amount", the firable
 * transitions as buttons, and the actions (share links, edit, archive, and a menu with
 * Status setzen, Versionen vergleichen, Löschen, Anonymisierung beantragen). Body: the
 * details, the answers by section (`app-answer-view`), the attachments, the history
 * (status changes and versions by day) and the comments.
 *
 * A transition with `addsToAgenda` opens the agenda dialog, which asks for the meeting.
 * "Bearbeiten" turns the sheet into the edit form (board Anträge-Bearbeiten): the bar
 * "Antrag bearbeiten · Speichern legt Version n+1 an" with Abbrechen and Speichern over
 * the fields of the form by section. A 422 of the server shows on its field.
 *
 * A comment is internal or public. Each comment shows its visibility. The composer
 * offers the internal visibility only with `application.manage`. Without it, a new
 * comment is public.
 *
 * RBAC here only gates the UX. The server decides.
 */
@Component({
  selector: 'app-applications-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SheetBarComponent,
    NgTemplateOutlet,
    RouterLink,
    FormsModule,
    FormlyForm,
    LocalizedDatePipe,
    TranslatePipe,
    AvatarComponent,
    EmptyStateComponent,
    FieldGroupComponent,
    FieldRowComponent,
    NoteComponent,
    RowMenuComponent,
    StatusTextComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    SegmentedComponent,
    SelectComponent,
    TabsComponent,
    CostCentreTreeComponent,
    ScrollFadeDirective,
    AttachmentsPanelComponent,
    AnswerViewComponent,
    HistoryComponent,
    ShareLinksDialogComponent,
    ForceStatusDialogComponent,
    AgendaDialogComponent,
  ],
  // The field types of the form (`provideFormly`) come with the component, so Formly is not
  // part of the initial bundle.
  providers: [provideFormly()],
  templateUrl: './applications-detail.component.html',
  styleUrl: './applications-detail.component.scss',
})
export class ApplicationsDetailComponent {
  private readonly api = inject(ApiClient);
  private readonly budgetApi = inject(BudgetTreeApi);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly railStatus = inject(RailStatusService);
  private readonly route = inject(ActivatedRoute);
  /** The link to the list pane. Absent when the detail runs without the list page. */
  private readonly page = inject(ApplicationsPageService, { optional: true });

  /** The list sits beside the detail: two columns, no tabs. */
  readonly split = computed(() => this.page?.split() ?? false);
  /** The route of the list pane: `/applications`, or `/tasks` on the tasks page. */
  readonly listPath = computed(() => this.page?.listPath() ?? ['/applications']);
  /** Phone: every header action goes into the menu. */
  readonly phone = mediaQuerySignal(MEDIA.phone);

  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly error = signal(false);

  readonly app = signal<Application | null>(null);
  readonly versions = signal<ApplicationVersion[]>([]);
  readonly comments = signal<ApplicationComment[]>([]);
  /** The status changes of the application, oldest first. */
  readonly timeline = signal<TimelineEntry[]>([]);
  /** The sections of the pinned form. Empty until it loaded, and on an error. */
  readonly sections = signal<FormSection[]>([]);
  /** The form is on its way; the answers wait for it, so no raw keys flash. */
  readonly formLoading = signal(true);
  /** The type of the application has a budget: drives `visibleIf: has_budget`. */
  readonly hasBudget = signal(false);
  /** The variables of `visibleIf` and `compute` besides the answers. */
  readonly formContext = computed(() => ({ has_budget: this.hasBudget() }));
  /** Field definitions of the effective form for labels and typed values. Empty on error. */
  readonly formFields = computed<FormFieldDef[]>(() => this.sections().flatMap((s) => s.fields));
  /** The same field definitions by key. The data rows and the version diff both
   *  look a key up, so they share one map. */
  private readonly fieldByKey = computed(
    () => new Map(this.formFields().map((f) => [f.key, f])),
  );

  readonly newComment = signal('');
  /** The visibility of the next comment. It goes back to public after each post. */
  readonly visibility = signal<CommentVisibility>('public');
  readonly visibilityOptions = computed<SegmentedOption[]>(() => [
    { value: 'public', label: this.i18n.translate('applications.comments.public') },
    { value: 'internal', label: this.i18n.translate('applications.comments.internal') },
  ]);
  readonly posting = signal(false);

  // Edit and delete of one comment. Both run in a dialog. The server allows the
  // author of the comment and a holder of `application.manage`. `isOwn` carries
  // the same author check the server makes, so the UI offers nothing that gives
  // a 403. Only the body changes. The visibility stays as written.
  readonly editingComment = signal<ApplicationComment | null>(null);
  readonly commentDraft = signal('');
  readonly savingComment = signal(false);
  readonly deletingComment = signal<ApplicationComment | null>(null);
  readonly removingComment = signal(false);

  /** The active tab of the narrow layout. */
  readonly tab = signal<DetailTab>('app');
  /** The number of attachments, from the panel. `null` until it loaded them. */
  readonly attachmentCount = signal<number | null>(null);

  /** Manual transitions that the server guard allows, plus the fire in flight. */
  readonly transitions = signal<Transition[]>([]);
  readonly firing = signal<Uuid | null>(null);
  /** The transition of the agenda dialog. */
  readonly agendaTransition = signal<Transition | null>(null);
  readonly agendaOpen = signal(false);
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

  // Force status is a privileged override that needs `application.force_status`. The
  // dialog loads the flow states itself.
  readonly canForceStatus = computed(() => this.auth.can('application.force_status'));
  readonly forceDialogOpen = signal(false);

  private readonly router = inject(Router);
  readonly canManage = computed(() => this.auth.can('application.manage'));
  /**
   * Delete is irreversible and needs `application.delete`. An admin holds it
   * through the role bypass. Any other role holds it through an explicit grant. The
   * server gates on the same key.
   */
  readonly canDelete = computed(() => this.auth.can('application.delete'));
  readonly canArchive = computed(() => this.auth.can('application.archive'));
  readonly archiving = signal(false);

  /**
   * Move the application out of the working list, or bring it back.
   *
   * Reversible and destructive of nothing, so unlike the delete and the erasure request
   * it asks for no confirmation: the way back is one click on the same button.
   */
  toggleArchived(): void {
    const current = this.app();
    if (!current || this.archiving()) return;
    const next = current.archivedAt === null;
    this.archiving.set(true);
    this.api.setApplicationArchived(current.id, next).subscribe({
      next: (updated) => {
        this.app.set(updated);
        this.archiving.set(false);
        this.page?.notify({ id: updated.id, kind: 'updated', source: 'detail' });
        this.toast.success(
          this.i18n.translate(next ? 'applications.archived' : 'applications.unarchived'),
        );
      },
      error: () => {
        this.archiving.set(false);
        this.toast.error(this.i18n.translate('applications.detail.error'));
      },
    });
  }
  /**
   * Public share links. `application.share` is its own permission on purpose: reading an
   * application and deciding it may be read by anyone holding a URL are different
   * decisions, and the server gates on the same key. The dialog does the rest.
   */
  readonly canShare = computed(() => this.auth.can('application.share'));
  readonly shareDialogOpen = signal(false);

  openShareDialog(): void {
    this.shareDialogOpen.set(true);
  }

  /**
   * One value of the version diff on the change line, formatted the way the answers
   * show the field. Cost positions give their summary ("3 Kostenpositionen ·
   * 395,00 €"). A long text, a table or an object of an unknown key gives `null`: the
   * line names only the field, and `fmtBlock` gives the value.
   *
   * The diff carries a key, not a field definition, so the type comes from the key.
   * A key the form does not define (an answer of an older form version) keeps the
   * plain text for a scalar.
   */
  readonly fmt = (value: unknown, key?: string): string | null => {
    const field = key === undefined ? undefined : this.fieldByKey().get(key);
    if (field?.type === 'positions') return this.positionsSummary(value);
    if (field && BLOCK_DIFF.has(field.type)) return null;
    if (!field && value !== null && typeof value === 'object') return null;
    const text = field
      ? formatAnswer(field, value, {
          lang: this.i18n.locale(),
          yes: this.i18n.translate('common.yes'),
          no: this.i18n.translate('common.no'),
        })
      : formatFieldValue(value);
    return text || '—';
  };

  /**
   * One value of the version diff as a block below the change line, or `null` when the
   * line holds it all. A text keeps its line breaks. The cost positions give one line
   * per position and one indented line per offer, so a changed offer shows too. A table
   * and an object of an unknown key give one line per row.
   */
  readonly fmtBlock = (value: unknown, key?: string): string | null => {
    const field = key === undefined ? undefined : this.fieldByKey().get(key);
    const block = field ? BLOCK_DIFF.has(field.type) : value !== null && typeof value === 'object';
    if (!block) return null;
    if (field?.type === 'positions') return this.positionsBlock(value) || '—';
    if (typeof value === 'string') return value.trim() ? value : '—';
    return rowLines(value) || '—';
  };

  /** "3 Kostenpositionen · 395,00 €"; the total counts the preferred offers. */
  private positionsSummary(value: unknown): string {
    const positions = normalizePositions(value);
    if (!positions.length) return '—';
    const t = this.i18n;
    const count = t.translate(
      positions.length === 1 ? 'apply.positions.countOne' : 'apply.positions.countOther',
      { count: positions.length },
    );
    return `${count} · ${this.money(positionsTotal(positions))}`;
  }

  /**
   * The cost positions, one line each ("Raummiete · 177,75 €"), with the offers below
   * ("– Studierendenwerk · 177,75 € · bevorzugt") and the reason of a position without
   * comparison offers.
   */
  private positionsBlock(value: unknown): string {
    const t = this.i18n;
    const lines: string[] = [];
    for (const p of normalizePositions(value)) {
      const name = p.label.trim() || t.translate('forms.positions.untitled');
      lines.push(`${name} · ${this.money(positionValue(p))}`);
      if (p.noOffers) {
        const reason = p.noOffersReason.trim();
        const short = t.translate('forms.positions.noOffersShort');
        lines.push(`   ${reason ? `${short}: ${reason}` : short}`);
      }
      for (const o of p.offers) {
        const parts = [o.label.trim() || '—', this.money(o.value)];
        if (o.preferred) parts.push(t.translate('forms.positions.preferred'));
        lines.push(`   – ${parts.join(' · ')}`);
      }
    }
    return lines.join('\n');
  }

  /** An amount in euro; a missing value counts as 0, as on the server. */
  private money(value: number | null): string {
    return formatEuro(Number(value), this.i18n.locale()) ?? '';
  }

  /** The label of a field of the diff, or its key when the form does not define it. */
  private fieldLabel(key: string): string {
    const field = this.fieldByKey().get(key);
    return field ? resolveI18n(field.label, this.i18n.locale()) : key;
  }

  /** The changed fields of a version as lines of the history. */
  private versionChanges(version: ApplicationVersion): HistoryChange[] {
    const t = (key: TranslationKey) => this.i18n.translate(key);
    if (!version.diff) {
      // Metadata view (A11): the keys of the changed fields, no values.
      return (version.changedKeys ?? []).map((key) => ({
        kind: 'warn',
        tag: t('applications.history.diff.changed'),
        label: this.fieldLabel(key),
      }));
    }
    // The long values below the line; a side the change does not have stays null.
    const detail = (
      key: string,
      sides: { old?: unknown; new?: unknown },
    ): HistoryChange['detail'] => {
      const old = 'old' in sides ? this.fmtBlock(sides.old, key) : null;
      const neu = 'new' in sides ? this.fmtBlock(sides.new, key) : null;
      return old === null && neu === null ? null : { old, new: neu };
    };
    return [
      ...version.diff.changed.map((c) => {
        const more = detail(c.key, { old: c.old, new: c.new });
        let old = this.fmt(c.old, c.key);
        let neu = this.fmt(c.new, c.key);
        // The same summary on both sides ("3 Kostenpositionen · 395,00 €" when an offer
        // text changed) says nothing: the line names the field, the blocks show it.
        if (more && old === neu) old = neu = null;
        return {
          kind: 'warn' as const,
          tag: t('applications.history.diff.changed'),
          label: this.fieldLabel(c.key),
          old,
          new: neu,
          detail: more,
        };
      }),
      ...version.diff.added.map((a) => ({
        kind: 'accent' as const,
        tag: t('applications.history.diff.added'),
        label: this.fieldLabel(a.key),
        new: this.fmt(a.value, a.key),
        detail: detail(a.key, { new: a.value }),
      })),
      ...version.diff.removed.map((r) => ({
        kind: 'error' as const,
        tag: t('applications.history.diff.removed'),
        label: this.fieldLabel(r.key),
        old: this.fmt(r.value, r.key),
        detail: detail(r.key, { old: r.value }),
      })),
    ];
  }

  /** The label of an actor: a name, "Antragsteller:in", "System · Fristen", …. */
  private actor(info: ActorInfo | null | undefined, legacy: string | null): string | null {
    return actorLabel(info, legacy, (key, params) => this.i18n.translate(key, params));
  }

  /**
   * "Verlauf": the status changes and the versions, by day (`app-history`).
   *
   * A status change shows the new state in its colour, the transition ("Übergang
   * „Prüfung beginnen“", A3) and the note. The first status event is the submission and
   * carries "Version 1". Every later version shows its changed fields with the old and
   * the new value.
   */
  readonly historyEntries = computed<HistoryEntry[]>(() => {
    const t = (key: TranslationKey, params?: Record<string, string | number>) =>
      this.i18n.translate(key, params);
    const events = [...this.timeline()].sort((a, b) => a.at.localeCompare(b.at));
    const versions = this.versions();
    const capture = this.app()?.capture ?? null;
    const entries: HistoryEntry[] = events.map((e, i) => {
      const lines: string[] = [];
      if (i === 0 && versions.some((v) => v.version === 1)) {
        lines.push(t('applications.history.version', { version: 1 }));
      }
      if (i === 0 && capture) {
        lines.push(t('applications.history.captured'));
        if (capture.intake) lines.push(t('applications.history.intake', { intake: capture.intake }));
      }
      if (e.transitionLabel) {
        lines.push(t('applications.history.transition', { label: e.transitionLabel }));
      }
      if (e.note) lines.push(e.note);
      // The vote that decided the status: a link, or a note when the meeting delete
      // took it along (the status stays).
      if (e.voteDeleted) lines.push(t('applications.history.voteDeleted'));
      return {
        at: e.at,
        icon: i === 0 ? 'send' : 'flow',
        title: e.toState?.label || e.label,
        kind: flowColorKind(e.toState?.color),
        actor: this.actor(e.actorInfo, e.actor),
        body: lines.join('\n') || null,
        link: e.voteId
          ? { label: t('applications.history.voteLink'), route: ['/voting', e.voteId] }
          : null,
      };
    });
    for (const v of versions) {
      if (v.version === 1 && events.length) continue;
      const changes = v.version === 1 ? [] : this.versionChanges(v);
      entries.push({
        at: v.at,
        icon: 'edit',
        title: t('applications.history.version', { version: v.version }),
        actor: this.actor(v.changedByInfo, v.changedBy),
        body:
          v.version === 1
            ? t('applications.history.initial')
            : changes.length
              ? null
              : t('applications.history.diff.none'),
        changes,
      });
    }
    return entries;
  });

  private id: Uuid = '';

  readonly title = computed(() =>
    applicationTitle(this.app()?.data, this.i18n.translate('applications.list.untitled')),
  );

  /** The application types, for "<Typ> · Version n". */
  private readonly types = signal<ApplicationType[]>([]);
  /** Gremium names from the meeting filter list, for a gremium the reader is not in. */
  private readonly filterGremien = signal<{ id: Uuid; name: string }[]>([]);
  private gremienRequested = false;

  /** "<Typ> · Version n" above the title. */
  readonly metaLine = computed(() => {
    const app = this.app();
    if (!app) return '';
    const type = this.types().find((t) => t.id === app.typeId)?.name;
    const version = this.i18n.translate('applications.detail.version', { version: app.version });
    return type ? `${type} · ${version}` : version;
  });

  /**
   * #11: the note of a captured application, as parts of one line: "Erfasst von <Name>
   * am <Datum>", "eingegangen am <Datum>" when the received date differs from the
   * capture day, and the free-text "Eingang". Null for an own submission.
   */
  readonly captureParts = computed<string[] | null>(() => {
    const cap = this.app()?.capture;
    if (!cap) return null;
    const t = (key: TranslationKey, params?: Record<string, string | number>) =>
      this.i18n.translate(key, params);
    const day = (d: Date) =>
      new Intl.DateTimeFormat(this.i18n.formatLocale(), { dateStyle: 'medium' }).format(d);
    const captured = new Date(cap.capturedAt);
    const name = this.actor(cap.capturedBy, null) ?? t('actor.deleted');
    const parts = [t('applications.capture.note', { name, date: day(captured) })];
    if (cap.receivedOn && cap.receivedOn !== localToday(captured)) {
      const [y, m, d] = cap.receivedOn.split('-').map(Number);
      parts.push(t('applications.capture.noteReceived', { date: day(new Date(y, m - 1, d)) }));
    }
    if (cap.intake) parts.push(cap.intake);
    return parts;
  });

  /** The name of the gremium of the application, or null when it is not known here. */
  readonly gremiumName = computed(() => {
    const id = this.app()?.gremiumId;
    if (!id) return null;
    const own = this.auth.gremien().find((g) => g.id === id)?.name;
    return own ?? this.filterGremien().find((g) => g.id === id)?.name ?? null;
  });

  /** The status of the application as coloured text. */
  readonly stateKind = computed(() => flowColorKind(this.app()?.state?.color));

  /** The look of each transition button: main action, tonal, or danger (a rejection). */
  readonly looks = computed(() => transitionLooks(this.transitions()));

  /** The data can change: the edit button and the menu item. The edit form needs the
   *  fields of the form, so the button waits for them. */
  readonly canEditData = computed(() => {
    const app = this.app();
    return !!app?.canEdit && !!app.state?.editAllowed && this.sections().length > 0;
  });

  /** The owner may ask for the anonymization of their data (GDPR Art. 17). */
  readonly canRequestErasure = computed(() => {
    const app = this.app();
    return !!app?.isOwner && !app.applicant?.anonymized;
  });

  /**
   * The header menu. On a phone it also holds the actions that wider screens show as
   * icon buttons (share links, edit, archive).
   */
  readonly menuSections = computed<RowMenuSection[]>(() => {
    const app = this.app();
    if (!app) return [];
    const t = (key: TranslationKey) => this.i18n.translate(key);
    const quick: RowMenuItem[] = [];
    if (this.phone()) {
      if (this.canShare()) quick.push({ id: 'share', label: t('applications.row.share'), icon: 'link' });
      if (this.canEditData()) quick.push({ id: 'edit', label: t('applications.detail.edit'), icon: 'edit' });
      if (this.canArchive()) {
        quick.push({
          id: 'archive',
          label: t(app.archivedAt ? 'applications.row.unarchive' : 'applications.row.archive'),
          icon: 'archive',
        });
      }
    }
    const more: RowMenuItem[] = [];
    if (this.canForceStatus()) {
      more.push({ id: 'force', label: t('applications.detail.forceStatus'), icon: 'flow' });
    }
    if (this.versions().length > 1) {
      more.push({ id: 'versions', label: t('applications.detail.compareVersions'), icon: 'history' });
    }
    const danger: RowMenuItem[] = [];
    if (this.canDelete()) {
      danger.push({ id: 'delete', label: t('applications.detail.delete'), icon: 'trash', danger: true });
    }
    if (this.canRequestErasure()) {
      danger.push({ id: 'erase', label: t('applications.detail.eraseRequest'), icon: 'user', danger: true });
    }
    return [{ items: quick }, { items: more }, { items: danger }].filter((sec) => sec.items.length);
  });

  /** The tabs of the narrow layout, with their counts. */
  readonly tabs = computed<TabItem[]>(() => [
    { id: 'app', label: this.i18n.translate('applications.detail.tab.app') },
    {
      id: 'history',
      label: this.i18n.translate('applications.detail.tab.history'),
      count: this.historyEntries().length,
    },
    {
      id: 'comments',
      label: this.i18n.translate('applications.detail.tab.comments'),
      count: this.comments().length,
    },
    {
      id: 'files',
      label: this.i18n.translate('applications.detail.tab.files'),
      count: this.attachmentCount(),
    },
  ]);

  constructor() {
    // Use `paramMap`, not `snapshot`. Angular reuses the component on a
    // detail-to-detail navigation, so the constructor does not run again. A snapshot
    // would keep the old `id`. The subscription reloads on every `id` change.
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.loadApplication(pm.get('id') ?? '');
    });
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (types) => this.types.set(types),
      error: () => this.types.set([]),
    });
    // The list pane changed this application (a row action): show the new state.
    this.page?.changes$.pipe(takeUntilDestroyed()).subscribe((change) => {
      if (change.source === 'list' && change.id === this.id && change.kind === 'updated') {
        this.refresh();
      }
    });
  }

  /** A tab of the narrow layout was chosen. */
  selectTab(id: string | null): void {
    if (id === 'app' || id === 'history' || id === 'comments' || id === 'files') this.tab.set(id);
  }

  /** An item of the header menu was chosen. */
  onMenu(item: RowMenuItem): void {
    const app = this.app();
    if (!app) return;
    switch (item.id) {
      case 'share':
        this.openShareDialog();
        break;
      case 'edit':
        this.startEdit(app);
        break;
      case 'archive':
        this.toggleArchived();
        break;
      case 'force':
        this.openForceDialog();
        break;
      case 'versions':
        this.showVersions();
        break;
      case 'delete':
        this.confirmDelete.set(true);
        break;
      case 'erase':
        this.confirmErase.set(true);
        break;
    }
  }

  /**
   * "Versionen vergleichen": the history holds every version with its changes. The tabs
   * switch to it; side by side the history section scrolls into view.
   */
  showVersions(): void {
    if (!this.split()) {
      this.tab.set('history');
      return;
    }
    const el = document.getElementById('ad-history');
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    el?.focus({ preventScroll: true });
  }

  /** Load the gremium names once, when the gremium is not one of the reader's own. */
  private resolveGremium(app: Application): void {
    if (!app.gremiumId || this.gremienRequested) return;
    if (this.auth.gremien().some((g) => g.id === app.gremiumId)) return;
    this.gremienRequested = true;
    this.api.listMeetingFilterGremien().subscribe({
      next: (list) => this.filterGremien.set(list),
      error: () => this.filterGremien.set([]),
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
    this.timeline.set([]);
    this.sections.set([]);
    this.formLoading.set(true);
    this.hasBudget.set(false);
    this.newComment.set('');
    this.visibility.set('public');
    this.editing.set(false);
    this.confirmDelete.set(false);
    this.notFound.set(false);
    this.error.set(false);
    this.editingComment.set(null);
    this.deletingComment.set(null);
    this.transitions.set([]);
    this.agendaOpen.set(false);
    this.attachmentCount.set(null);
    this.tab.set('app');
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
        this.resolveGremium(app);
        this.loadAux();
        // Take the effective form from the pinned version of the application, not from
        // the active one. The labels and the edit fields then match the data that the
        // server validates.
        this.api.applicationForm(app.id).subscribe({
          next: (eff) => {
            if (seq !== this.loadSeq) return;
            this.sections.set(eff.sections);
            this.hasBudget.set(eff.hasBudget);
            this.formLoading.set(false);
          },
          error: () => {
            // Without the form the answers show as plain text under "Weitere Angaben".
            if (seq !== this.loadSeq) return;
            this.sections.set([]);
            this.formLoading.set(false);
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
    this.api.timeline(this.id, { quiet: true }).subscribe({
      next: (events) => {
        if (seq === this.loadSeq) this.timeline.set(events);
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
    // The "Kostenstelle" row and the dialog picker both need the cost-centre tree. Every
    // reader loads it (the server scopes it), so the row names the cost centre also for a
    // reader without `application.manage`. Only the "Ändern" button needs that right.
    if (this.canManage()) {
      this.budgetChoice.set(this.app()?.budgetId ?? '');
      this.fiscalChoice.set(this.app()?.fiscalYearId ?? '');
    }
    this.budgetApi.tree().subscribe({
      next: (tree) => {
        if (seq !== this.loadSeq) return;
        this.budgetTree.set(tree);
        // The row needs the fiscal years of the current cost centre.
        this.loadFiscalYears(this.app()?.budgetId ?? null);
      },
      error: () => {
        if (seq === this.loadSeq) this.budgetTree.set([]);
      },
    });
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
          this.changed();
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

  amount(app: Application): string {
    if (app.amount === null) return this.i18n.translate('applications.detail.notProvided');
    const value = Number(app.amount);
    if (Number.isNaN(value)) return app.amount;
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: app.currency ?? 'EUR',
    }).format(value);
  }

  startEdit(app: Application): void {
    // A reader without the PII right gets `data` without the isPII fields (O21), and
    // the server names them in `hiddenKeys`. The form leaves them out, because the
    // server keeps their stored values anyway. A key that is only missing from `data`
    // was never answered, so that field stays editable.
    this.editFields.set(
      toFormlySections(this.sections(), this.i18n.locale(), this.formContext(), {
        omitKeys: app.hiddenKeys ?? [],
      }),
    );
    this.editModel = structuredClone(app.data);
    this.editForm = new FormGroup({});
    this.editing.set(true);
  }

  cancelEdit(): void {
    this.editing.set(false);
  }

  /**
   * Save the edit as a new version (PATCH). An invalid form shows its errors and sends
   * nothing. A 422 of the server shows on the fields it names (for example a cost
   * position without an offer, D12); a 409 means the state no longer allows an edit.
   */
  saveEdit(): void {
    if (this.savingEdit()) return;
    clearServerErrors(this.editFields());
    if (this.editForm.invalid) {
      this.editForm.markAllAsTouched();
      this.toast.error(this.i18n.translate('applications.edit.invalid'));
      this.revealError();
      return;
    }
    this.savingEdit.set(true);
    this.api.updateApplication(this.id, { ...this.editModel }).subscribe({
      next: (updated) => {
        this.savingEdit.set(false);
        this.editing.set(false);
        this.toast.success(
          this.i18n.translate('applications.edit.saved', { version: updated.version }),
        );
        this.changed();
      },
      error: (err: { status?: number; error?: ProblemDetail | null }) => {
        this.savingEdit.set(false);
        if (err.status === 422 && err.error?.errors?.length) {
          const placed = applyServerErrors(this.editFields(), err.error.errors, (key) =>
            this.i18n.translate(key),
          );
          if (placed) {
            this.toast.error(this.i18n.translate('applications.edit.invalid'));
            this.revealError();
            return;
          }
        }
        const key =
          err.status === 409 ? 'applications.detail.locked' : 'applications.detail.saveFailed';
        this.toast.error(this.i18n.translate(key));
      },
    });
  }

  /** Scroll the first field with an error into view, after the form drew it. */
  private revealError(): void {
    setTimeout(() => {
      const el = document.querySelector<HTMLElement>(
        '.ad__edit [aria-invalid="true"], .ad__edit [role="alert"]',
      );
      el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
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
        this.page?.notify({ id: this.id, kind: 'deleted', source: 'detail' });
        void this.router.navigate([...this.listPath()], { queryParamsHandling: 'preserve' });
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

  /** Open the force-status dialog. It loads the flow states itself. */
  openForceDialog(): void {
    this.forceDialogOpen.set(true);
  }

  /** The force-status dialog set a state: load the application again. */
  onForced(): void {
    this.changed();
  }

  /** Display name of a comment: the author, or a fallback based on the role. */
  protected authorName(comment: ApplicationComment): string {
    const info =
      comment.authorInfo ?? (comment.authorKind === 'applicant' ? { kind: 'applicant' as const } : null);
    return (
      this.actor(info, comment.author) ??
      this.i18n.translate('applications.comments.author.committee')
    );
  }

  /** Enter sends the comment. Shift+Enter makes a line break.
   *  The Angular `keydown.enter` binding matches the unmodified Enter only. */
  protected onComposerEnter(event: Event): void {
    this.submitComment(event);
  }

  protected setVisibility(value: string | null): void {
    this.visibility.set(value === 'internal' ? 'internal' : 'public');
  }

  submitComment(event: Event): void {
    event.preventDefault();
    const body = this.newComment().trim();
    if (!body || this.posting()) return;
    this.posting.set(true);
    // Without `application.manage` the composer has no toggle, so the comment is public.
    const visibility = this.canManage() ? this.visibility() : 'public';
    this.api.addComment(this.id, body, visibility).subscribe({
      next: (created) => {
        this.comments.update((list) => [...list, created]);
        this.newComment.set('');
        this.visibility.set('public');
        this.posting.set(false);
        this.toast.success(this.i18n.translate('applications.comments.added'));
      },
      error: () => {
        this.posting.set(false);
        this.toast.error(this.i18n.translate('applications.comments.error'));
      },
    });
  }

  // --- edit / delete of a comment -----------------------------------------

  /** The author of the comment, or a manager, may change it. The server checks
   *  the same rule, so no visible control ends in a 403. */
  protected canEditComment(comment: ApplicationComment): boolean {
    return comment.isOwn || this.canManage();
  }

  protected openEditComment(comment: ApplicationComment): void {
    this.commentDraft.set(comment.body);
    this.editingComment.set(comment);
  }

  protected closeEditComment(): void {
    this.editingComment.set(null);
  }

  /** Translation key for a failed comment change. 403 and 404 read as reasons. */
  private commentErrorKey(status: number | undefined): TranslationKey {
    if (status === 403) return 'applications.comments.forbidden';
    if (status === 404) return 'applications.comments.gone';
    return 'applications.comments.error';
  }

  /** PATCH the body of the comment. The visibility is not patchable. */
  protected saveComment(): void {
    const comment = this.editingComment();
    const body = this.commentDraft().trim();
    if (!comment || !body || this.savingComment()) return;
    this.savingComment.set(true);
    this.api.updateComment(this.id, comment.id, body).subscribe({
      next: (updated) => {
        this.savingComment.set(false);
        this.editingComment.set(null);
        this.comments.update((list) => list.map((c) => (c.id === updated.id ? updated : c)));
        this.toast.success(this.i18n.translate('applications.comments.updated'));
      },
      error: (err: { status?: number }) => {
        this.savingComment.set(false);
        this.toast.error(this.i18n.translate(this.commentErrorKey(err.status)));
      },
    });
  }

  protected askDeleteComment(comment: ApplicationComment): void {
    this.deletingComment.set(comment);
  }

  protected doDeleteComment(): void {
    const comment = this.deletingComment();
    if (!comment || this.removingComment()) return;
    this.removingComment.set(true);
    this.api.deleteComment(this.id, comment.id).subscribe({
      next: () => {
        this.removingComment.set(false);
        this.deletingComment.set(null);
        this.comments.update((list) => list.filter((c) => c.id !== comment.id));
        this.toast.success(this.i18n.translate('applications.comments.deleted'));
      },
      error: (err: { status?: number }) => {
        this.removingComment.set(false);
        this.toast.error(this.i18n.translate(this.commentErrorKey(err.status)));
      },
    });
  }

  /** Fire a manual transition with POST /transition, then reload the application.
   *  The server checks the guard again. A 403 or a 409 answer shows a toast and
   *  refreshes. */
  fire(t: Transition): void {
    if (this.firing() !== null) return;
    // A transition onto the agenda needs the meeting: the dialog asks for it and fires.
    if (t.addsToAgenda) {
      this.agendaTransition.set(t);
      this.agendaOpen.set(true);
      return;
    }
    this.firing.set(t.id);
    this.api.fireTransition(this.id, { transitionId: t.id }).subscribe({
      next: () => {
        this.firing.set(null);
        this.toast.success(this.i18n.translate('applications.actions.success'));
        this.changed();
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
        this.changed();
      },
    });
  }

  /** The agenda dialog fired its transition. */
  onAgendaDone(): void {
    this.changed();
  }

  /** This pane changed the application: load it again and tell the list pane. */
  private changed(): void {
    this.refresh();
    this.page?.notify({ id: this.id, kind: 'updated', source: 'detail' });
  }

  /** Reload the application and the dependent sections after a transition. The task
   *  count of the navigation changes with the state, so it is asked again too. */
  private refresh(): void {
    this.railStatus.refresh();
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

/**
 * A table answer, or an object of an unknown key, as lines: one row each, the cells as
 * "Spalte: Wert" joined by a dot. A scalar row keeps its text.
 */
function rowLines(value: unknown): string {
  const cell = (v: unknown): string =>
    v !== null && typeof v === 'object' ? JSON.stringify(v) : formatFieldValue(v);
  const row = (r: unknown): string =>
    r !== null && typeof r === 'object' && !Array.isArray(r)
      ? Object.entries(r as Record<string, unknown>)
          .map(([k, v]) => `${k}: ${cell(v)}`)
          .join(' · ')
      : cell(r);
  if (Array.isArray(value)) return value.map(row).join('\n');
  if (value !== null && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${cell(v)}`)
      .join('\n');
  }
  return formatFieldValue(value);
}
