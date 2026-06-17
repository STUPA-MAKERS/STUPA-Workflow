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
  ApplicationVersion,
  CommentVisibility,
  FormFieldDef,
  Transition,
  Uuid,
} from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import { toFormlyFields } from '@shared/forms/formly-mapper';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { SelectComponent, type SelectOption } from '@shared/ui';
import { CardComponent } from '@shared/ui/card/card.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';
import { IconComponent } from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import {
  BudgetTreeApi,
  type BudgetTreeNode,
  type FiscalYear,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import { AttachmentsPanelComponent } from './attachments-panel.component';
import { applicationTitle, formatFieldValue } from './applications.util';

/** Vergleichsangebot bzw. Kostenposition für die strukturierte Detailanzeige (#1). */
interface DetailOffer {
  label?: string;
  value?: number | null;
  preferred?: boolean;
}
interface DetailPosition {
  label: string;
  offers: DetailOffer[];
}

/**
 * Antrags-Detail (T-31, overview §4): Felder, Versions-Historie/Diff, Kommentare
 * (intern/öffentlich) und RBAC-gegatete Statuswechsel-Aktionen mit Bestätigung
 * und 409-Handling.
 *
 * RBAC ist UX-Gating (nicht autoritativ — der Server entscheidet): die Aktionen
 * und die interne Kommentar-Sichtbarkeit erscheinen nur mit `application.manage`.
 *
 * Anhänge sind hier bewusst ein **Platzhalter** — Upload/Download über signierte
 * URLs samt Scan-Status liefert T-13 (files); der Endpunkt existiert noch nicht.
 */
@Component({
  selector: 'app-applications-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
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
  /** Feld-Definitionen der effektiven Form — für Labels/typisierte Werte (sonst leer). */
  readonly formFields = signal<FormFieldDef[]>([]);

  readonly newComment = signal('');
  readonly visibility = signal<CommentVisibility>('public');
  readonly posting = signal(false);

  /** Verfügbare manuelle Übergänge (vom Server guard-gefiltert) + laufender Fire. */
  readonly transitions = signal<Transition[]>([]);
  readonly firing = signal<Uuid | null>(null);
  readonly canTransition = computed(() => this.auth.can('application.transition'));

  /** Kostenstellen-Zuordnung (#17): Baum, Dialog-Auswahl, laufende Zuweisung. */
  protected readonly budgetTree = signal<BudgetTreeNode[]>([]);
  protected readonly budgetChoice = signal('');
  protected readonly assigningBudget = signal(false);
  protected readonly budgetDialogOpen = signal(false);
  /** HHJ-Auswahl (#tz/fiscal): HHJ des Top-Budgets der gewählten Kostenstelle; leer =
   *  „automatisch" (Server leitet das eine aktive HHJ ab, sonst 422). */
  protected readonly fiscalYears = signal<FiscalYear[]>([]);
  protected readonly fiscalChoice = signal('');
  /** ``budgetId`` → „VOLLER-PFAD – Name" (Badge der aktuellen Kostenstelle, #det). */
  private readonly budgetLabels = computed(
    () => new Map(flattenBudgetOptions(this.budgetTree()).map((o) => [o.value, o.label])),
  );
  protected budgetLabel(id: string | null | undefined): string {
    return (id && this.budgetLabels().get(id)) || '';
  }
  /** ``fiscalYearId`` → Anzeige (z. B. ``2026``) der aktuell geladenen HHJ. */
  private readonly fiscalLabels = computed(
    () => new Map(this.fiscalYears().map((y) => [y.id, y.display])),
  );
  protected fiscalLabel(id: string | null | undefined): string {
    return (id && this.fiscalLabels().get(id)) || '';
  }
  /** Dropdown-Optionen: „Automatisch" + alle HHJ des Top-Budgets (inaktive markiert). */
  protected readonly fiscalOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('applications.budget.fiscalAuto') },
    ...this.fiscalYears().map((y) => ({
      value: y.id,
      label: y.active
        ? y.display
        : `${y.display} (${this.i18n.translate('applications.budget.fiscalInactive')})`,
    })),
  ]);
  /** Top-Budget (Wurzel) finden, dessen Teilbaum die Kostenstelle enthält. */
  private topLevelIdOf(budgetId: string): string | null {
    const contains = (n: BudgetTreeNode): boolean =>
      n.id === budgetId || (n.children?.some(contains) ?? false);
    for (const root of this.budgetTree()) if (contains(root)) return root.id;
    return null;
  }
  /** HHJ des Top-Budgets der gewählten Kostenstelle laden (Dropdown + Badge). */
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
  /** Kostenstelle im Dialog gewählt: HHJ-Liste neu laden; HHJ-Auswahl nur dann
   *  beibehalten, wenn die ursprüngliche Kostenstelle wieder gewählt ist. */
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

  // Inline-Bearbeitung (Ersteller:in/Verwalter:in, #24) + Löschen.
  readonly editing = signal(false);
  readonly editFields = signal<FormlyFieldConfig[]>([]);
  readonly savingEdit = signal(false);
  editForm = new FormGroup({});
  editModel: Record<string, unknown> = {};
  readonly confirmDelete = signal(false);
  readonly deleting = signal(false);
  readonly confirmErase = signal(false);
  readonly requestingErasure = signal(false);

  private readonly router = inject(Router);
  readonly canManage = computed(() => this.auth.can('application.manage'));
  /** Löschen ist admin-only (irreversibel). */
  readonly isAdmin = computed(() => this.auth.roles().includes('admin'));
  readonly fmt = formatFieldValue;

  private id: Uuid = '';

  readonly title = computed(() =>
    applicationTitle(this.app()?.data, this.i18n.translate('applications.list.untitled')),
  );

  constructor() {
    // `paramMap` (nicht `snapshot`): bei Detail→Detail-Navigation reused Angular
    // die Komponente, der Konstruktor läuft dann **nicht** erneut — ein Snapshot
    // bliebe auf der alten `id` stehen. Das Abo lädt bei jedem `id`-Wechsel neu.
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.loadApplication(pm.get('id') ?? '');
    });
  }

  /** Lauf-Nummer der Ladevorgänge: verspätete Antworten eines früheren Antrags
   *  (schneller Wechsel zwischen Detailseiten) dürfen den aktuellen nicht
   *  überschreiben — jede Antwort prüft, ob sie noch zum letzten Ladelauf gehört. */
  private loadSeq = 0;

  private loadApplication(id: Uuid): void {
    this.id = id;
    const seq = ++this.loadSeq;
    // Zustand für die (ggf. neue) id zurücksetzen, damit nichts Altes durchblitzt.
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
    this.api.getApplication(id).subscribe({
      next: (app) => {
        if (seq !== this.loadSeq) return;
        this.app.set(app);
        this.loading.set(false);
        this.loadAux();
        // Effektive Form aus der **gepinnten** Version des Antrags (nicht der aktiven) —
        // so passen Labels/Edit-Felder zu den Daten, gegen die der Server validiert.
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

  /** Versionen/Kommentare/verfügbare Übergänge nachladen — Fehler degradieren still
   *  zu leer. Übergänge nur mit der nötigen Permission (Server filtert zusätzlich). */
  private loadAux(): void {
    const seq = this.loadSeq;
    this.api.versions(this.id).subscribe({
      next: (v) => {
        if (seq === this.loadSeq) this.versions.set(v);
      },
      error: () => {},
    });
    this.api.comments(this.id).subscribe({
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
    // Kostenstellen-Zuordnung (#17): Baum laden (Badge-Label + Dialog-Picker).
    if (this.canManage()) {
      this.budgetChoice.set(this.app()?.budgetId ?? '');
      this.fiscalChoice.set(this.app()?.fiscalYearId ?? '');
      this.budgetApi.tree().subscribe({
        next: (tree) => {
          if (seq !== this.loadSeq) return;
          this.budgetTree.set(tree);
          // HHJ-Liste für die aktuelle Kostenstelle laden (Badge-Anzeige des HHJ).
          this.loadFiscalYears(this.app()?.budgetId ?? null);
        },
        error: () => {
          if (seq === this.loadSeq) this.budgetTree.set([]);
        },
      });
    }
  }

  /** Kostenstelle zuordnen/lösen (#17): POST /assign-budget → Antrag neu laden. */
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

  /** Antragsdaten als Label/Wert-Zeilen: Feld-Definition → Label + typisierter Wert;
   *  unbekannte Keys roh; `title` (im Kopf gezeigt) + reine Anzeigefelder weglassen. */
  dataEntries(app: Application): { key: string; label: string; value: string }[] {
    const lang = this.i18n.locale();
    const byKey = new Map(this.formFields().map((f) => [f.key, f]));
    const rows: { key: string; label: string; value: string }[] = [];
    const seen = new Set<string>();

    const pushField = (f: FormFieldDef): void => {
      if (f.type === 'markdown' || f.type === 'computed') return;
      // Kostenpositionen werden als eigener Block (Positionen + Angebote) gezeigt.
      if (f.type === 'positions') return;
      if (f.key === 'title') return;
      if (!(f.key in app.data)) return;
      seen.add(f.key);
      rows.push({ key: f.key, label: resolveI18n(f.label, lang), value: this.formatByField(f, app.data[f.key]) });
    };

    for (const f of this.formFields()) pushField(f);
    // Daten ohne passende Feld-Definition trotzdem zeigen (roh) — außer `title`.
    for (const [key, value] of Object.entries(app.data)) {
      if (seen.has(key) || key === 'title' || byKey.has(key)) continue;
      rows.push({ key, label: key, value: formatFieldValue(value) });
    }
    return rows;
  }

  /** Einen Wert anhand seines Feldtyps anzeigefreundlich formatieren. */
  private formatByField(field: FormFieldDef, value: unknown): string {
    if (value === null || value === undefined || value === '') return '—';
    const lang = this.i18n.locale();
    if (field.type === 'positions') return this.formatPositions(value);
    if (field.type === 'checkbox' && typeof value === 'boolean') {
      return this.i18n.translate(value ? 'common.yes' : 'common.no');
    }
    if (field.type === 'select') {
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

  /** Kostenpositionen-Felder (falls vorhanden) als strukturierter Block für die
   *  Detailansicht: je Position die Vergleichsangebote inkl. bevorzugtem (#1). */
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
      }));
      out.push({ key: f.key, label: resolveI18n(f.label, lang), positions });
    }
    return out;
  }

  /** Wert eines Vergleichsangebots / einer Position als Währung. */
  money(value: number | null | undefined): string {
    const n = Number(value ?? 0);
    return new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: 'EUR',
    }).format(Number.isFinite(n) ? n : 0);
  }

  /** Positionswert = Wert des bevorzugten Angebots. */
  positionValue(p: DetailPosition): number {
    return p.offers.find((o) => o.preferred)?.value ?? 0;
  }

  /** Σ über alle Positionswerte. */
  positionsTotal(positions: DetailPosition[]): number {
    return positions.reduce((s, p) => s + this.positionValue(p), 0);
  }

  /** Kostenpositionen kompakt: Anzahl Positionen + Σ der bevorzugten Werte. */
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

  // --- edit / delete (#24) -------------------------------------------------
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

  /** DSGVO Art. 17: Löschung der eigenen Antragsdaten beantragen (Magic-Link-Sicht). */
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

  /** Anzeigename eines Kommentars (Autor oder rollenbasierter Fallback). */
  protected authorName(comment: ApplicationComment): string {
    if (comment.author) return comment.author;
    return this.i18n.translate(
      comment.authorKind === 'applicant'
        ? 'applications.comments.author.applicant'
        : 'applications.comments.author.committee',
    );
  }

  /** Initiale(n) für den Chat-Avatar. */
  protected initial(name: string): string {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    const first = parts[0][0];
    const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
    return (first + last).toUpperCase();
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

  /** Einen manuellen Übergang feuern (#28): POST /transition → Antrag neu laden.
   *  Der Server prüft den Guard erneut (403/409 möglich → Toast + Refresh). */
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

  /** Antrag + abhängige Sektionen nach einem Übergang neu laden. */
  private refresh(): void {
    const seq = this.loadSeq;
    this.api.getApplication(this.id).subscribe({
      next: (app) => {
        if (seq !== this.loadSeq) return;
        this.app.set(app);
        this.loadAux();
      },
      error: () => {},
    });
  }
}
