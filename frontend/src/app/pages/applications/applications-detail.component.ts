import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
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
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { CardComponent } from '@shared/ui/card/card.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AttachmentsPanelComponent } from './attachments-panel.component';
import { applicationTitle, formatFieldValue, stateBadgeVariant } from './applications.util';

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
    DatePipe,
    TranslatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    DialogComponent,
    AttachmentsPanelComponent,
  ],
  template: `
    @if (loading()) {
      <p class="det__status" aria-live="polite">{{ 'applications.detail.loading' | t }}</p>
    } @else if (notFound()) {
      <p class="det__status" role="alert">{{ 'applications.detail.notFound' | t }}</p>
    } @else if (error()) {
      <p class="det__status det__status--error" role="alert">
        {{ 'applications.detail.error' | t }}
      </p>
    } @else if (app(); as application) {
      <header class="det__head">
        <h1 class="det__title">{{ title() }}</h1>
        <div class="det__meta">
          @if (application.state) {
            <app-badge [variant]="stateVariant(application.state.category)">
              {{ application.state.label }}
            </app-badge>
          }
          <span class="det__version">
            {{ 'applications.detail.version' | t: { version: application.version } }}
          </span>
        </div>
        <dl class="det__facts">
          <div>
            <dt>{{ 'applications.detail.created' | t }}</dt>
            <dd><time [attr.datetime]="application.createdAt">{{ application.createdAt | date: 'medium' }}</time></dd>
          </div>
          <div>
            <dt>{{ 'applications.detail.updated' | t }}</dt>
            <dd><time [attr.datetime]="application.updatedAt">{{ application.updatedAt | date: 'medium' }}</time></dd>
          </div>
          @if (application.applicant) {
            <div>
              <dt>{{ 'applications.detail.applicant' | t }}</dt>
              <dd>
                @if (application.applicant.anonymized) {
                  {{ 'applications.detail.anonymized' | t }}
                } @else {
                  {{ application.applicant.name || application.applicant.email || ('applications.detail.notProvided' | t) }}
                }
              </dd>
            </div>
          }
          <div>
            <dt>{{ 'applications.detail.amount' | t }}</dt>
            <dd>{{ amount(application) }}</dd>
          </div>
        </dl>
      </header>

      <!-- Antragsdaten -->
      <app-card [heading]="'applications.detail.data.title' | t">
        @if (dataEntries(application).length) {
          <dl class="det__data">
            @for (entry of dataEntries(application); track entry.key) {
              <div class="det__dataRow">
                <dt>{{ entry.label }}</dt>
                <dd>{{ entry.value }}</dd>
              </div>
            }
          </dl>
        } @else {
          <p class="det__muted">{{ 'applications.detail.data.empty' | t }}</p>
        }
      </app-card>

      <!-- Approval-State (#28): Annehmen/Ablehnen (Server prüft Rolle im Gremium) -->
      @if (application.state?.kind === 'approval') {
        <app-card [heading]="'applications.approval.title' | t">
          <p class="det__muted">{{ 'applications.approval.lead' | t }}</p>
          <div class="det__actions">
            <app-button variant="primary" size="sm" [loading]="approving()" (click)="submitApproval('accept')">
              {{ 'applications.approval.accept' | t }}
            </app-button>
            <app-button variant="danger" size="sm" [loading]="approving()" (click)="submitApproval('reject')">
              {{ 'applications.approval.reject' | t }}
            </app-button>
          </div>
        </app-card>
      }

      <!-- Statuswechsel-Aktionen (RBAC: application.manage) -->
      @if (canManage()) {
        <app-card [heading]="'applications.actions.title' | t">
          @if (transitions().length) {
            <div class="det__actions">
              @for (transition of transitions(); track transition.id) {
                <app-button variant="secondary" size="sm" (click)="openConfirm(transition)">
                  {{ transitionLabel(transition) }}
                </app-button>
              }
            </div>
          } @else {
            <p class="det__muted">{{ 'applications.actions.none' | t }}</p>
          }
        </app-card>
      }

      <!-- Versions-Historie + Diff -->
      <app-card [heading]="'applications.history.title' | t">
        @if (versions().length > 1) {
          <ol class="det__history">
            @for (version of versions(); track version.version) {
              <li class="det__version-item">
                <div class="det__version-head">
                  <strong>{{ 'applications.history.version' | t: { version: version.version } }}</strong>
                  @if (version.changedBy) {
                    <span class="det__muted">{{ 'applications.history.by' | t: { actor: version.changedBy } }}</span>
                  }
                  <time class="det__muted" [attr.datetime]="version.at">{{ version.at | date: 'short' }}</time>
                </div>
                @if (!version.diff) {
                  <p class="det__muted">{{ 'applications.history.initial' | t }}</p>
                } @else if (isEmptyDiff(version)) {
                  <p class="det__muted">{{ 'applications.history.diff.none' | t }}</p>
                } @else {
                  <ul class="det__diff">
                    @for (change of version.diff.changed; track change.key) {
                      <li>
                        <app-badge variant="warning">{{ 'applications.history.diff.changed' | t }}</app-badge>
                        <code>{{ change.key }}</code>:
                        <del>{{ fmt(change.old) }}</del> → <ins>{{ fmt(change.new) }}</ins>
                      </li>
                    }
                    @for (added of version.diff.added; track added.key) {
                      <li>
                        <app-badge variant="success">{{ 'applications.history.diff.added' | t }}</app-badge>
                        <code>{{ added.key }}</code>: <ins>{{ fmt(added.value) }}</ins>
                      </li>
                    }
                    @for (removed of version.diff.removed; track removed.key) {
                      <li>
                        <app-badge variant="danger">{{ 'applications.history.diff.removed' | t }}</app-badge>
                        <code>{{ removed.key }}</code>: <del>{{ fmt(removed.value) }}</del>
                      </li>
                    }
                  </ul>
                }
              </li>
            }
          </ol>
        } @else {
          <p class="det__muted">{{ 'applications.history.empty' | t }}</p>
        }
      </app-card>

      <!-- Kommentare -->
      <app-card [heading]="'applications.comments.title' | t">
        @if (comments().length) {
          <ul class="det__comments">
            @for (comment of comments(); track comment.id) {
              <li class="det__comment">
                <div class="det__comment-head">
                  <span class="det__comment-author">
                    {{ comment.author || (comment.authorKind === 'applicant'
                      ? ('applications.comments.author.applicant' | t)
                      : ('applications.comments.author.committee' | t)) }}
                  </span>
                  <app-badge [variant]="comment.isPublic ? 'info' : 'neutral'">
                    {{ (comment.isPublic ? 'applications.comments.public' : 'applications.comments.internal') | t }}
                  </app-badge>
                  <time class="det__muted" [attr.datetime]="comment.at">{{ comment.at | date: 'short' }}</time>
                </div>
                <p class="det__comment-body">{{ comment.body }}</p>
              </li>
            }
          </ul>
        } @else {
          <p class="det__muted">{{ 'applications.comments.empty' | t }}</p>
        }

        <form class="det__commentForm" (submit)="submitComment($event)">
          <label class="field__label" [for]="'det-comment'">{{ 'applications.comments.add' | t }}</label>
          <textarea
            id="det-comment"
            class="field__control det__textarea"
            rows="3"
            [placeholder]="'applications.comments.placeholder' | t"
            [ngModel]="newComment()"
            (ngModelChange)="newComment.set($event)"
            name="comment"
          ></textarea>
          <div class="det__commentActions">
            @if (canManage()) {
              <label class="det__visibility">
                {{ 'applications.comments.visibility' | t }}
                <select
                  class="field__control"
                  [ngModel]="visibility()"
                  (ngModelChange)="visibility.set($event)"
                  name="visibility"
                >
                  <option value="public">{{ 'applications.comments.public' | t }}</option>
                  <option value="internal">{{ 'applications.comments.internal' | t }}</option>
                </select>
              </label>
            }
            <app-button
              type="submit"
              size="sm"
              [disabled]="!newComment().trim()"
              [loading]="posting()"
            >
              {{ 'applications.comments.send' | t }}
            </app-button>
          </div>
        </form>
      </app-card>

      <!-- Anhänge (T-13-Contract): Upload + signierte Download-URLs + Scan-Status -->
      <app-attachments-panel [applicationId]="application.id" [canUpload]="canManage()" />
    }

    <app-dialog
      [open]="pending() !== null"
      [title]="'applications.actions.confirm.title' | t"
      [closeLabel]="'action.close' | t"
      (closed)="cancelConfirm()"
    >
      @if (pending(); as transition) {
        <p>{{ 'applications.actions.confirm.body' | t: { label: transition.label } }}</p>
        <label class="field__label" [for]="'det-note'">{{ 'applications.actions.confirm.note' | t }}</label>
        <textarea
          id="det-note"
          class="field__control det__textarea"
          rows="2"
          [placeholder]="'applications.actions.confirm.notePlaceholder' | t"
          [ngModel]="note()"
          (ngModelChange)="note.set($event)"
          name="note"
        ></textarea>
      }
      <div dialog-footer>
        <app-button variant="ghost" size="sm" (click)="cancelConfirm()">
          {{ 'action.cancel' | t }}
        </app-button>
        <app-button variant="primary" size="sm" [loading]="firing()" (click)="confirmTransition()">
          {{ 'applications.actions.confirm.submit' | t }}
        </app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .det__status {
        color: var(--color-text-muted);
        padding: var(--space-5) 0;
      }
      .det__status--error {
        color: var(--color-danger);
      }
      .det__head {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .det__meta {
        display: flex;
        align-items: center;
        gap: var(--space-3);
      }
      .det__version {
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .det__facts {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
        gap: var(--space-3) var(--space-5);
        margin: 0;
      }
      .det__facts dt {
        font-size: var(--fs-xs);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--color-text-muted);
      }
      .det__facts dd {
        margin: 0;
        color: var(--color-text);
      }
      .det__data,
      .det__history,
      .det__comments {
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .det__dataRow {
        display: grid;
        grid-template-columns: minmax(8rem, 14rem) 1fr;
        gap: var(--space-4);
        padding: var(--space-2) 0;
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .det__dataRow dt {
        color: var(--color-text-muted);
        font-weight: var(--fw-medium);
      }
      .det__dataRow dd {
        margin: 0;
        word-break: break-word;
      }
      .det__muted {
        color: var(--color-text-muted);
      }
      .det__actions {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-2);
      }
      .det__history {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
      }
      .det__version-head {
        display: flex;
        align-items: baseline;
        gap: var(--space-3);
        flex-wrap: wrap;
        margin-bottom: var(--space-2);
      }
      .det__diff {
        margin: 0;
        padding: 0;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        font-size: var(--fs-sm);
      }
      .det__diff code {
        background: var(--color-surface-sunken);
        padding: 0 var(--space-1);
        border-radius: var(--radius-sm);
      }
      .det__diff del {
        color: var(--color-danger);
      }
      .det__diff ins {
        color: var(--color-success);
        text-decoration: none;
      }
      .det__comments {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
        margin-bottom: var(--space-5);
      }
      .det__comment {
        padding-bottom: var(--space-3);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .det__comment-head {
        display: flex;
        align-items: baseline;
        gap: var(--space-3);
        flex-wrap: wrap;
        margin-bottom: var(--space-1);
      }
      .det__comment-author {
        font-weight: var(--fw-semibold);
      }
      .det__comment-body {
        margin: 0;
        white-space: pre-wrap;
      }
      .det__commentForm {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .field__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text-muted);
      }
      .field__control {
        padding: var(--space-2) var(--space-3);
        background: var(--color-bg);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
        font-family: inherit;
      }
      .field__control:focus-visible {
        outline: 2px solid var(--color-primary);
        outline-offset: 1px;
      }
      .det__textarea {
        resize: vertical;
      }
      .det__commentActions {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: var(--space-3);
        flex-wrap: wrap;
      }
      .det__visibility {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        font-size: var(--fs-sm);
        color: var(--color-text-muted);
      }
    `,
  ],
})
export class ApplicationsDetailComponent {
  private readonly api = inject(ApiClient);
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
  readonly transitions = signal<Transition[]>([]);
  /** Feld-Definitionen der effektiven Form — für Labels/typisierte Werte (sonst leer). */
  readonly formFields = signal<FormFieldDef[]>([]);

  readonly newComment = signal('');
  readonly visibility = signal<CommentVisibility>('public');
  readonly posting = signal(false);

  readonly pending = signal<Transition | null>(null);
  readonly note = signal('');
  readonly firing = signal(false);
  readonly approving = signal(false);

  readonly canManage = computed(() => this.auth.can('application.manage'));
  readonly stateVariant = stateBadgeVariant;
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

  private loadApplication(id: Uuid): void {
    this.id = id;
    // Zustand für die (ggf. neue) id zurücksetzen, damit nichts Altes durchblitzt.
    this.app.set(null);
    this.versions.set([]);
    this.comments.set([]);
    this.transitions.set([]);
    this.formFields.set([]);
    this.pending.set(null);
    this.note.set('');
    this.newComment.set('');
    this.visibility.set('public');
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
        this.app.set(app);
        this.loading.set(false);
        this.loadAux();
        // Effektive Form für Feld-Labels/typisierte Werte (still degradieren → rohe Keys).
        this.api.effectiveForm?.(app.typeId).subscribe({
          next: (eff) => this.formFields.set(eff.sections.flatMap((s) => s.fields)),
          error: () => this.formFields.set([]),
        });
      },
      error: (err: { status?: number }) => {
        this.loading.set(false);
        if (err.status === 404) this.notFound.set(true);
        else this.error.set(true);
      },
    });
  }

  /** Versions/Kommentare/Transitions nachladen — Fehler degradieren still zu leer. */
  private loadAux(): void {
    this.api.versions(this.id).subscribe({ next: (v) => this.versions.set(v), error: () => {} });
    this.api.comments(this.id).subscribe({ next: (c) => this.comments.set(c), error: () => {} });
    if (this.canManage()) {
      this.api.transitions(this.id).subscribe({
        next: (t) => this.transitions.set(t),
        error: () => this.transitions.set([]),
      });
    }
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

  /** Übergangs-Label mit Fallback (leeres i18n-Label → generisch „Weiter“). */
  transitionLabel(transition: Transition): string {
    return transition.label?.trim() || this.i18n.translate('applications.actions.advance');
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

  openConfirm(transition: Transition): void {
    this.note.set('');
    this.pending.set(transition);
  }

  cancelConfirm(): void {
    this.pending.set(null);
  }

  confirmTransition(): void {
    const transition = this.pending();
    if (!transition || this.firing()) return;
    this.firing.set(true);
    const note = this.note().trim() || null;
    this.api.fireTransition(this.id, { transitionId: transition.id, note }).subscribe({
      next: () => {
        this.firing.set(false);
        this.pending.set(null);
        this.toast.success(this.i18n.translate('applications.actions.success'));
        this.refresh();
      },
      error: (err: { status?: number }) => {
        this.firing.set(false);
        this.pending.set(null);
        // 409: Status hat sich geändert oder ein Guard schlug fehl → Liste der
        // erlaubten Übergänge ist veraltet; Detail + Aktionen neu laden.
        const key =
          err.status === 409 ? 'applications.actions.conflict' : 'applications.actions.error';
        this.toast.error(this.i18n.translate(key));
        this.refresh();
      },
    });
  }

  /** Approval-State entscheiden (#28): Annehmen/Ablehnen → POST /approval. */
  submitApproval(decision: 'accept' | 'reject'): void {
    if (this.approving()) return;
    this.approving.set(true);
    this.api.submitApproval(this.id, decision).subscribe({
      next: () => {
        this.approving.set(false);
        this.toast.success(this.i18n.translate('applications.actions.success'));
        this.refresh();
      },
      error: (err: { status?: number }) => {
        this.approving.set(false);
        const key =
          err.status === 403
            ? 'applications.approval.forbidden'
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
    this.api.getApplication(this.id).subscribe({
      next: (app) => {
        this.app.set(app);
        this.loadAux();
      },
      error: () => {},
    });
  }
}
