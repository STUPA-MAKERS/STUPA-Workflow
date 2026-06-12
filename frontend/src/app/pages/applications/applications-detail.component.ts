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
import { CardComponent } from '@shared/ui/card/card.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';
import { IconComponent } from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import {
  BudgetTreeApi,
  type BudgetTreeNode,
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
    CostCentreTreeComponent,
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
        <div class="det__titleRow">
          <h1 class="det__title">{{ title() }}</h1>
          @if (application.canEdit && !editing()) {
            <div class="det__ownerActions">
              @if (application.state?.editAllowed) {
                <app-button variant="secondary" size="sm" (click)="startEdit(application)">{{ 'applications.detail.edit' | t }}</app-button>
              }
              @if (isAdmin()) {
                <app-button variant="danger" size="sm" (click)="confirmDelete.set(true)">{{ 'applications.detail.delete' | t }}</app-button>
              }
            </div>
          }
        </div>
        <div class="det__meta">
          @if (application.state) {
            <app-badge [color]="application.state.color">
              {{ application.state.label }}
            </app-badge>
          }
          @if (application.budgetId && budgetLabel(application.budgetId)) {
            <app-badge variant="neutral">{{ budgetLabel(application.budgetId) }}</app-badge>
          }
          <span class="det__version">
            {{ 'applications.detail.version' | t: { version: application.version } }}
          </span>
          @if (canManage()) {
            <app-button class="det__ccBtn" variant="ghost" size="sm" (click)="openBudgetDialog()">
              <span class="det__ccBtnInner">
                <app-icon name="euro" [size]="15" />
                {{ application.budgetId ? ('applications.budget.change' | t) : ('applications.budget.assign' | t) }}
              </span>
            </app-button>
          }
        </div>
        <dl class="det__facts">
          <div>
            <dt>{{ 'applications.detail.created' | t }}</dt>
            <dd><time [attr.datetime]="application.createdAt">{{ application.createdAt | ldate: 'medium' }}</time></dd>
          </div>
          <div>
            <dt>{{ 'applications.detail.updated' | t }}</dt>
            <dd><time [attr.datetime]="application.updatedAt">{{ application.updatedAt | ldate: 'medium' }}</time></dd>
          </div>
          @if (application.applicant) {
            <div>
              <dt>{{ 'applications.detail.applicant' | t }}</dt>
              <dd>{{ application.applicant.name || ('applications.detail.notProvided' | t) }}</dd>
            </div>
            @if (application.applicant.email) {
              <div>
                <dt>{{ 'applications.detail.email' | t }}</dt>
                <dd><a [attr.href]="'mailto:' + application.applicant.email">{{ application.applicant.email }}</a></dd>
              </div>
            }
          }
          <div>
            <dt>{{ 'applications.detail.amount' | t }}</dt>
            <dd>{{ amount(application) }}</dd>
          </div>
        </dl>
      </header>

      <div class="det__layout" [class.det__layout--editing]="editing()">
      <!-- LINKS: Übergänge als schwebende Karte (#det) -->
      <aside class="det__rail det__rail--left">
        @if (canTransition() && transitions().length) {
          <app-card [heading]="'applications.transitions.title' | t">
            <div class="det__transitions">
              @for (t of transitions(); track t.id) {
                <app-button
                  [color]="t.color"
                  [block]="true"
                  [loading]="firing() === t.id"
                  [disabled]="firing() !== null && firing() !== t.id"
                  (click)="fire(t)"
                >
                  {{ t.label || ('applications.transitions.fallback' | t) }}
                </app-button>
              }
            </div>
          </app-card>
        }
      </aside>

      <!-- MITTE: Antragsdaten + Historie + Anhänge -->
      <div class="det__center">
      <!-- Antragsdaten (Ansicht oder Inline-Bearbeitung der Ersteller:in/Verwalter:in) -->
      <app-card [heading]="'applications.detail.data.title' | t">
        @if (editing()) {
          <formly-form [form]="editForm" [fields]="editFields()" [model]="editModel" />
          <div class="det__editActions">
            <app-button variant="ghost" size="sm" (click)="cancelEdit()">{{ 'applications.detail.cancel' | t }}</app-button>
            <app-button size="sm" [disabled]="editForm.invalid" [loading]="savingEdit()" (click)="saveEdit()">{{ 'applications.detail.save' | t }}</app-button>
          </div>
        } @else if (dataEntries(application).length || positionEntries(application).length) {
          @if (dataEntries(application).length) {
            <dl class="det__data">
              @for (entry of dataEntries(application); track entry.key) {
                <div class="det__dataRow">
                  <dt>{{ entry.label }}</dt>
                  <dd>{{ entry.value }}</dd>
                </div>
              }
            </dl>
          }
          <!-- Kostenpositionen mit Vergleichsangeboten (#1) -->
          @for (pf of positionEntries(application); track pf.key) {
            <section class="det__positions">
              <h3 class="det__positions-h">{{ pf.label }}</h3>
              @for (p of pf.positions; track $index) {
                <div class="det__pos">
                  <div class="det__pos-head">
                    <strong>{{ p.label || ('applications.detail.positionUntitled' | t) }}</strong>
                    <span class="det__pos-val">{{ money(positionValue(p)) }}</span>
                  </div>
                  <ul class="det__offers">
                    @for (o of p.offers; track $index) {
                      <li class="det__offer" [class.det__offer--pref]="o.preferred">
                        <span class="det__offer-label">{{ o.label || '—' }}</span>
                        @if (o.preferred) {
                          <app-badge variant="success">{{ 'apply.positions.preferred' | t }}</app-badge>
                        }
                        <span class="det__offer-val">{{ money(o.value) }}</span>
                      </li>
                    }
                  </ul>
                </div>
              }
              <p class="det__pos-total"><strong>{{ 'apply.positions.total' | t }}: {{ money(positionsTotal(pf.positions)) }}</strong></p>
            </section>
          }
        } @else {
          <p class="det__muted">{{ 'applications.detail.data.empty' | t }}</p>
        }
      </app-card>

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
                  <time class="det__muted" [attr.datetime]="version.at">{{ version.at | ldate: 'short' }}</time>
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

      <!-- Anhänge (T-13-Contract): Upload + signierte Download-URLs + Scan-Status -->
      <app-attachments-panel [applicationId]="application.id" [canUpload]="canManage()" />
      </div><!-- /det__center -->

      <!-- RECHTS: Kommentare als Chat (#det) -->
      <aside class="det__rail det__rail--right">
        <section class="det__chat" [attr.aria-label]="'applications.comments.title' | t">
          <header class="det__chatHead">{{ 'applications.comments.title' | t }}</header>
          <div class="det__chatScroll">
            @for (comment of comments(); track comment.id) {
              <article
                class="det__msg"
                [class.det__msg--own]="comment.authorKind !== 'applicant'"
              >
                <span class="det__avatar" aria-hidden="true">{{ initial(authorName(comment)) }}</span>
                <div class="det__msgBody">
                  <div class="det__msgTop">
                    <span class="det__msgAuthor">{{ authorName(comment) }}</span>
                    <time class="det__msgTime" [attr.datetime]="comment.at">{{ comment.at | ldate: 'short' }}</time>
                  </div>
                  <div class="det__bubble">{{ comment.body }}</div>
                </div>
              </article>
            } @empty {
              <p class="det__muted det__chatEmpty">{{ 'applications.comments.empty' | t }}</p>
            }
          </div>

          <form class="det__composer" (submit)="submitComment($event)">
            <div class="det__composerRow">
              <textarea
                class="det__composerInput"
                rows="1"
                [placeholder]="'applications.comments.placeholder' | t"
                [ngModel]="newComment()"
                (ngModelChange)="newComment.set($event)"
                name="comment"
                [attr.aria-label]="'applications.comments.add' | t"
              ></textarea>
              <app-button
                type="submit"
                size="sm"
                [iconOnly]="true"
                [ariaLabel]="'applications.comments.send' | t"
                [disabled]="!newComment().trim()"
                [loading]="posting()"
              >
                <app-icon name="send" [size]="15" />
              </app-button>
            </div>
          </form>
        </section>
      </aside>
      </div><!-- /det__layout -->
    }

    <app-dialog
      [open]="confirmDelete()"
      [title]="'applications.detail.deleteTitle' | t"
      [closeLabel]="'applications.detail.cancel' | t"
      (closed)="confirmDelete.set(false)"
    >
      <p>{{ 'applications.detail.deleteConfirm' | t }}</p>
      <div dialog-footer>
        <app-button variant="ghost" size="sm" (click)="confirmDelete.set(false)">{{ 'applications.detail.cancel' | t }}</app-button>
        <app-button variant="danger" size="sm" [loading]="deleting()" (click)="doDelete()">{{ 'applications.detail.delete' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Kostenstelle zuordnen (#17): Tree-Picker im Dialog. -->
    <app-dialog
      [open]="budgetDialogOpen()"
      [title]="'applications.budget.title' | t"
      [closeLabel]="'applications.detail.cancel' | t"
      (closed)="budgetDialogOpen.set(false)"
    >
      <p class="det__muted">{{ 'applications.budget.lead' | t }}</p>
      <div class="det__ccTree">
        <app-cost-centre-tree
          [nodes]="budgetTree()"
          [selectedId]="budgetChoice()"
          [allLabel]="'applications.budget.none' | t"
          [ariaLabel]="'applications.budget.field' | t"
          (picked)="budgetChoice.set($event)"
        />
      </div>
      <div dialog-footer>
        <app-button variant="ghost" size="sm" (click)="budgetDialogOpen.set(false)">{{ 'applications.detail.cancel' | t }}</app-button>
        <app-button
          size="sm"
          [loading]="assigningBudget()"
          [disabled]="budgetChoice() === (app()?.budgetId ?? '')"
          (click)="assignBudget()"
        >{{ 'applications.budget.save' | t }}</app-button>
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
        /* Auf Body-Breite zentriert — fluchtet mit der Mittelspalte des Layouts. */
        width: 100%;
        max-width: var(--layout-max-width);
        margin-inline: auto;
      }
      .det__titleRow {
        display: flex;
        align-items: start;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
      }
      .det__title {
        margin: 0;
      }
      .det__ownerActions {
        display: flex;
        gap: var(--space-2);
      }
      .det__editActions {
        display: flex;
        justify-content: flex-end;
        gap: var(--space-2);
        margin-top: var(--space-3);
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
      /* Edit-Formular: Formly-Felder vertikal Luft geben (Image #5: Spacing). */
      formly-form {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
      }
      /* Kostenpositionen-Block (#1) */
      .det__positions {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        margin-top: var(--space-4);
      }
      .det__positions-h {
        margin: 0;
        font-size: var(--fs-md);
      }
      .det__pos {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        padding: var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
      }
      .det__pos-head {
        display: flex;
        justify-content: space-between;
        gap: var(--space-3);
      }
      .det__pos-val {
        font-variant-numeric: tabular-nums;
      }
      .det__offers {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      .det__offer {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        font-size: var(--fs-sm);
      }
      .det__offer-label {
        flex: 1;
        min-width: 0;
      }
      .det__offer-val {
        font-variant-numeric: tabular-nums;
        color: var(--color-text-muted);
      }
      .det__offer--pref .det__offer-val {
        color: var(--color-text);
        font-weight: var(--fw-medium);
      }
      .det__pos-total {
        margin: 0;
        font-variant-numeric: tabular-nums;
      }
      .det__actions {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-2);
        margin-top: var(--space-3);
      }
      .det__ccBtnInner {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
      }
      .det__ccTree {
        margin-top: var(--space-3);
        max-height: 50vh;
        overflow-y: auto;
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        padding: var(--space-2);
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

      /* --- Breakout-Layout: Übergänge + Chat schweben in den Rändern, Inhalt mittig
             auf Body-Breite (wie Baum/Charts im Budget-Tab, #det). --- */
      .det__layout {
        display: grid;
        grid-template-columns:
          minmax(11rem, 1fr)
          minmax(0, var(--layout-max-width))
          minmax(16rem, 1fr);
        gap: var(--space-5);
        align-items: start;
      }
      .det__center {
        min-width: 0;
        width: 100%;
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .det__rail {
        position: sticky;
        top: calc(var(--layout-header-height) + var(--space-4));
        min-width: 0;
        width: 100%;
      }
      .det__rail--left {
        justify-self: end;
        max-width: 15rem;
      }
      .det__rail--right {
        justify-self: start;
        max-width: 24rem;
      }
      .det__railLead {
        font-size: var(--fs-sm);
        margin: 0 0 var(--space-3);
      }
      .det__transitions {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      /* Bearbeiten: Ränder ausblenden, Formular volle Breite. */
      .det__layout--editing {
        grid-template-columns: 1fr;
      }
      .det__layout--editing .det__rail {
        display: none;
      }
      @media (max-width: 70rem) {
        .det__layout {
          grid-template-columns: 1fr;
        }
        .det__rail {
          position: static;
        }
      }

      /* --- Chat (Kommentare) — eigenständiges Panel (#det) --- */
      .det__chat {
        display: flex;
        flex-direction: column;
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        background: var(--color-surface);
        overflow: hidden;
        max-height: calc(100vh - var(--layout-header-height) - 6rem);
      }
      .det__chatHead {
        padding: var(--space-3) var(--space-4);
        font-weight: var(--fw-semibold);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .det__chatScroll {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        overflow-y: auto;
        padding: var(--space-4);
        min-height: 5rem;
      }
      .det__chatEmpty {
        margin: auto;
        text-align: center;
        font-size: var(--fs-sm);
        padding: var(--space-4) 0;
      }
      .det__msg {
        display: flex;
        gap: var(--space-2);
        max-width: 90%;
        align-self: flex-start;
      }
      .det__msg--own {
        align-self: flex-end;
        flex-direction: row-reverse;
      }
      .det__avatar {
        flex: 0 0 auto;
        width: 1.75rem;
        height: 1.75rem;
        border-radius: 50%;
        display: grid;
        place-items: center;
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
        background: var(--color-surface-sunken);
        color: var(--color-text-muted);
      }
      .det__msg--own .det__avatar {
        background: var(--color-primary-subtle);
        color: var(--color-primary);
      }
      .det__msgBody {
        display: flex;
        flex-direction: column;
        gap: 3px;
        min-width: 0;
      }
      .det__msg--own .det__msgBody {
        align-items: flex-end;
      }
      .det__msgTop {
        display: flex;
        align-items: baseline;
        gap: var(--space-2);
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .det__msgAuthor {
        font-weight: var(--fw-semibold);
        color: var(--color-text);
      }
      .det__intern {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        color: var(--color-warning, #c08a2a);
      }
      .det__msgTime {
        white-space: nowrap;
      }
      .det__bubble {
        padding: var(--space-2) var(--space-3);
        border-radius: 0 var(--radius-lg) var(--radius-lg) var(--radius-lg);
        background: var(--color-surface-sunken);
        white-space: pre-wrap;
        word-break: break-word;
        font-size: var(--fs-sm);
        line-height: 1.5;
      }
      .det__msg--own .det__bubble {
        border-radius: var(--radius-lg) 0 var(--radius-lg) var(--radius-lg);
        background: var(--color-primary-subtle);
      }
      .det__msg--internal .det__bubble {
        background: transparent;
        border: var(--border-width) dashed var(--color-border-strong);
      }
      .det__composer {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        padding: var(--space-3) var(--space-4);
        border-top: var(--border-width) solid var(--color-border);
      }
      .det__visToggle {
        display: inline-flex;
        align-self: flex-start;
        padding: 2px;
        gap: 2px;
        background: var(--color-surface-sunken);
        border-radius: var(--radius-pill);
      }
      .det__visToggle button {
        border: 0;
        background: transparent;
        color: var(--color-text-muted);
        font: inherit;
        font-size: var(--fs-xs);
        padding: var(--space-1) var(--space-3);
        border-radius: var(--radius-pill);
        cursor: pointer;
      }
      .det__visToggle button.is-active {
        background: var(--color-surface);
        color: var(--color-text);
        box-shadow: var(--shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.2));
      }
      .det__composerRow {
        display: flex;
        align-items: flex-end;
        gap: var(--space-2);
      }
      .det__composerInput {
        flex: 1;
        min-width: 0;
        resize: none;
        max-height: 8rem;
        padding: var(--space-2) var(--space-3);
        background: var(--color-bg);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-lg);
        font: inherit;
        font-size: var(--fs-sm);
        line-height: 1.4;
      }
      .det__composerInput:focus-visible {
        outline: 2px solid var(--color-primary);
        outline-offset: 1px;
      }

      /* --- Edit-Formular: konsistente vertikale Abstände (#det Image 7) --- */
      formly-form formly-field {
        display: block;
      }
      formly-form formly-field + formly-field {
        margin-top: var(--space-4);
      }

      /* --- Mobil (≤768px): Ränder in voller Breite stapeln, Zeilen einspaltig --- */
      @media (max-width: 768px) {
        .det__meta {
          flex-wrap: wrap;
        }
        .det__ownerActions {
          flex-wrap: wrap;
        }
        .det__rail--left,
        .det__rail--right {
          max-width: none;
          justify-self: stretch;
        }
        .det__dataRow {
          grid-template-columns: 1fr;
          gap: var(--space-1);
        }
        .det__diff li {
          word-break: break-word;
        }
        .det__chat {
          max-height: 70vh;
        }
      }
      formly-form formly-group > formly-field + formly-field {
        margin-top: var(--space-3);
      }
    `,
  ],
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
  /** ``budgetId`` → „VOLLER-PFAD – Name" (Badge der aktuellen Kostenstelle, #det). */
  private readonly budgetLabels = computed(
    () => new Map(flattenBudgetOptions(this.budgetTree()).map((o) => [o.value, o.label])),
  );
  protected budgetLabel(id: string | null | undefined): string {
    return (id && this.budgetLabels().get(id)) || '';
  }
  protected openBudgetDialog(): void {
    this.budgetChoice.set(this.app()?.budgetId ?? '');
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
      this.budgetApi.tree().subscribe({
        next: (tree) => {
          if (seq === this.loadSeq) this.budgetTree.set(tree);
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
    this.budgetApi.assignBudget(this.id, this.budgetChoice() || null).subscribe({
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
