import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  type OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  Attendance,
  AttendanceStatus,
  Meeting,
  MeetingVote,
  Protocol,
  Uuid,
} from '@core/api/models';
import { WsService, type MeetingChannel } from '@core/ws/ws.service';
import type { ServerMessage } from '@core/ws/ws-messages';
import { BadgeComponent, type BadgeVariant } from '@shared/ui/badge/badge.component';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { CardComponent } from '@shared/ui/card/card.component';
import {
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminOptionsService } from '../../pages/admin/admin-options.service';
import { antragSnippet, insertAt, renderMarkdown, voteSnippet } from './meetings.util';

/** Wartezeit nach der letzten Eingabe, bevor das Protokoll automatisch gespeichert wird (#56). */
const AUTOSAVE_DELAY_MS = 1000;

/**
 * Sitzungssteuerung + Protokoll-Editor (T-33, flows §5/§7).
 *
 *  - **Sitzungssteuerung** (RBAC `meeting.manage`): aktiven Antrag setzen, Votes
 *    live öffnen/schließen, Sitzungs-Status (live/geschlossen). Der Live-Stream
 *    (`/ws/meetings/{id}`) hält Status/Tally/Ergebnis ohne Reload aktuell und
 *    synchronisiert mit dem Beamer (api.md §4).
 *  - **Protokoll-Editor** (RBAC `protocol.write`): Markdown mit Snippet-Einfügen
 *    für Anträge/Abstimmungen (pytex-Shortcodes) + Live-Vorschau; `finalize`
 *    löst PDF/Versand aus (status `final` + Link).
 *
 * RBAC ist hier UX-Gating (nicht autoritativ) — der Server prüft jede Aktion.
 */
@Component({
  selector: 'app-meetings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    SelectComponent,
    DatepickerComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
    DatePipe,
  ],
  template: `
    <header class="mtg__head">
      <h1 class="mtg__title">{{ 'meetings.title' | t }}</h1>
      @if (meeting(); as m) {
        <div class="mtg__meta">
          <span class="mtg__name">{{ m.title }}</span>
          @if (m.date) {
            <span class="mtg__muted">{{ m.date | date: 'mediumDate' }}{{ m.startTime ? ', ' + m.startTime : '' }}</span>
          }
          <app-badge [variant]="statusVariant(m.status)">
            {{ statusKey(m.status) | t }}
          </app-badge>
        </div>
      }
    </header>

    @if (!canManage() && !canWrite()) {
      <p class="mtg__status" role="alert">{{ 'rbac.forbidden' | t }}</p>
    } @else if (loading()) {
      <p class="mtg__status" aria-live="polite">{{ 'meetings.loading' | t }}</p>
    } @else if (error()) {
      <p class="mtg__status mtg__status--error" role="alert">{{ 'meetings.error' | t }}</p>
    } @else if (meeting(); as m) {
      <!-- Sitzungssteuerung nur für die Sitzungsleitung (Vorstand/Schriftführung) (#Meetings). -->
      @if (canManage() && !m.canControl) {
        <p class="mtg__muted mtg__hint" role="note">{{ 'meetings.control.leadOnly' | t }}</p>
      }

      <!-- Vorab-Terminierung geplanter Sitzungen (#7) -->
      @if (canManage() && m.canControl && m.status === 'planned') {
        <app-card [heading]="'meetings.plan.title' | t">
          <p class="mtg__lead">{{ 'meetings.plan.lead' | t }}</p>
          <div class="mtg__planRow">
            <app-datepicker
              [label]="'meetings.plan.date' | t"
              [ngModel]="planDate()"
              (ngModelChange)="planDate.set($event)"
              name="planDate"
            />
            <label class="mtg__paneLabel" for="mtg-plan-time">{{ 'meetings.create.time' | t }}</label>
            <input
              id="mtg-plan-time"
              class="mtg__input"
              type="time"
              [ngModel]="planTime()"
              (ngModelChange)="planTime.set($event)"
              name="planTime"
            />
            <app-button
              size="sm"
              [loading]="savingDate()"
              [disabled]="!planDate()"
              (click)="savePlannedDate()"
            >
              {{ 'meetings.plan.save' | t }}
            </app-button>
          </div>
        </app-card>
      }

      <!-- Sitzungssteuerung -->
      @if (canManage() && m.canControl) {
        <app-card [heading]="'meetings.control.title' | t">
          <p class="mtg__lead">{{ 'meetings.control.lead' | t }}</p>
          <div class="mtg__statusActions" role="group" [attr.aria-label]="'meetings.control.session' | t">
            <app-button
              variant="secondary"
              size="sm"
              [disabled]="m.status === 'live'"
              (click)="setStatus('live')"
            >
              {{ 'meetings.control.open' | t }}
            </app-button>
            <app-button
              variant="secondary"
              size="sm"
              [disabled]="m.status === 'closed'"
              (click)="setStatus('closed')"
            >
              {{ 'meetings.control.closeSession' | t }}
            </app-button>
          </div>

          @if (m.votes.length) {
            <ul class="mtg__votes">
              @for (vote of m.votes; track vote.id) {
                <li class="mtg__vote" [class.mtg__vote--active]="vote.applicationId === m.activeApplicationId">
                  <div class="mtg__voteHead">
                    <span class="mtg__voteTitle">{{ vote.title || vote.applicationId }}</span>
                    <app-badge [variant]="voteVariant(vote.status)">
                      {{ voteStatusKey(vote.status) | t }}
                    </app-badge>
                    @if (vote.applicationId === m.activeApplicationId) {
                      <app-badge variant="primary">{{ 'meetings.vote.active' | t }}</app-badge>
                    }
                    @if (vote.result) {
                      <app-badge variant="info">{{ vote.result }}</app-badge>
                    }
                  </div>
                  @if (vote.counts) {
                    <dl class="mtg__tally" [attr.aria-label]="'meetings.vote.tally' | t">
                      @for (entry of countEntries(vote); track entry.key) {
                        <div [class.mtg__tally--leading]="entry.key === vote.leading">
                          <dt>{{ entry.key }}</dt>
                          <dd>{{ entry.value }}</dd>
                        </div>
                      }
                    </dl>
                  }
                  <div class="mtg__voteActions">
                    <app-button
                      variant="ghost"
                      size="sm"
                      [disabled]="vote.applicationId === m.activeApplicationId"
                      (click)="setActive(vote.applicationId)"
                    >
                      {{ 'meetings.vote.setActive' | t }}
                    </app-button>
                    @if (vote.status !== 'open') {
                      <app-button
                        variant="primary"
                        size="sm"
                        [disabled]="vote.status === 'closed'"
                        (click)="openVote(vote.id)"
                      >
                        {{ 'meetings.vote.open' | t }}
                      </app-button>
                    } @else {
                      <app-button variant="danger" size="sm" (click)="closeVote(vote.id)">
                        {{ 'meetings.vote.close' | t }}
                      </app-button>
                    }
                  </div>
                </li>
              }
            </ul>
          } @else {
            <p class="mtg__muted">{{ 'meetings.control.noVotes' | t }}</p>
          }
        </app-card>
      }

      <!-- Protokoll-Editor -->
      @if (canWrite()) {
        <app-card [heading]="'meetings.protocol.title' | t">
          @if (!protocol()) {
            <p class="mtg__muted">{{ 'meetings.protocol.none' | t }}</p>
            <app-button size="sm" [loading]="loadingProtocol()" (click)="loadProtocol()">
              {{ 'meetings.protocol.create' | t }}
            </app-button>
          } @else if (protocol(); as proto) {
            <div class="mtg__protoMeta">
              <app-badge [variant]="proto.isFinal ? 'success' : 'neutral'">
                {{ (proto.isFinal ? 'meetings.protocol.final' : 'meetings.protocol.draft') | t }}
              </app-badge>
              @if (proto.pdfUrl) {
                <a class="mtg__pdf" [href]="proto.pdfUrl" target="_blank" rel="noopener">
                  {{ 'meetings.protocol.pdf' | t }}
                </a>
              }
            </div>

            <!-- Snippet-Werkzeugleiste -->
            @if (!proto.isFinal && m.votes.length) {
              <div class="mtg__snippets" role="group" [attr.aria-label]="'meetings.protocol.snippets' | t">
                <span class="mtg__snippetsLabel">{{ 'meetings.protocol.snippets' | t }}</span>
                @for (vote of m.votes; track vote.id) {
                  <app-button variant="ghost" size="sm" (click)="insertAntrag(vote)">
                    + {{ 'meetings.protocol.snippetAntrag' | t }}: {{ vote.title || vote.applicationId }}
                  </app-button>
                  <app-button variant="ghost" size="sm" (click)="insertVote(vote)">
                    + {{ 'meetings.protocol.snippetVote' | t }}: {{ vote.title || vote.applicationId }}
                  </app-button>
                }
              </div>
            }

            <div class="mtg__editor">
              <div class="mtg__pane">
                <label class="mtg__paneLabel" [for]="'mtg-md'">{{ 'meetings.protocol.markdown' | t }}</label>
                <textarea
                  id="mtg-md"
                  class="mtg__textarea"
                  rows="16"
                  [disabled]="proto.isFinal"
                  [placeholder]="'meetings.protocol.placeholder' | t"
                  [ngModel]="markdown()"
                  (ngModelChange)="onMarkdownChange($event)"
                  (keyup)="onCaret($event)"
                  (click)="onCaret($event)"
                  (select)="onCaret($event)"
                  name="markdown"
                ></textarea>
              </div>
              <div class="mtg__pane">
                <span class="mtg__paneLabel">{{ 'meetings.protocol.preview' | t }}</span>
                <div class="mtg__preview" aria-live="polite" [innerHTML]="previewHtml()"></div>
              </div>
            </div>

            <div class="mtg__protoActions">
              @if (!proto.isFinal) {
                <!-- Auto-Speichern (#56): kein manueller Save-Button, Status-Anzeige. -->
                <span class="mtg__saveState" [attr.data-state]="saveState()" aria-live="polite">
                  @switch (saveState()) {
                    @case ('saving') { {{ 'meetings.protocol.saving' | t }} }
                    @case ('saved') { ✓ {{ 'meetings.protocol.saved' | t }} }
                    @case ('error') { {{ 'meetings.protocol.saveFailed' | t }} }
                    @default {
                      @if (dirty()) { {{ 'meetings.protocol.unsaved' | t }} }
                    }
                  }
                </span>
                <app-button
                  variant="primary"
                  size="sm"
                  [disabled]="dirty() || saveState() === 'saving'"
                  [loading]="finalizing()"
                  (click)="finalize()"
                >
                  {{ 'meetings.protocol.finalize' | t }}
                </app-button>
                @if (dirty() || saveState() === 'saving') {
                  <span class="mtg__muted mtg__hint">{{ 'meetings.protocol.saveFirst' | t }}</span>
                }
              } @else {
                <p class="mtg__muted">{{ 'meetings.protocol.finalizedHint' | t }}</p>
              }
            </div>
          }
        </app-card>
      }

      <!-- Anwesenheit (#Meetings/#55/#56) -->
      @if (attendance().length) {
        <app-card [heading]="'meetings.attendance.title' | t">
          <p class="mtg__lead">
            {{ (m.canControl ? 'meetings.attendance.leadLead' : 'meetings.attendance.lead') | t }}
          </p>
          <ul class="mtg__att">
            @for (a of attendance(); track a.principalId) {
              <li class="mtg__attRow">
                <span class="mtg__attName">
                  {{ a.displayName || a.email || a.principalId }}
                  @if (a.isSelf) { <span class="mtg__attYou">{{ 'meetings.attendance.you' | t }}</span> }
                </span>
                @if (m.canControl || a.isSelf) {
                  <span class="mtg__attBtns" role="group" [attr.aria-label]="'meetings.attendance.title' | t">
                    @for (s of attendanceStatuses; track s) {
                      <app-button
                        [variant]="a.status === s ? attBtnVariant(s) : 'ghost'"
                        size="sm"
                        [disabled]="savingAttendance()"
                        (click)="setAttendance(a, s)"
                      >
                        {{ attendanceKey(s) | t }}
                      </app-button>
                    }
                  </span>
                } @else {
                  <app-badge [variant]="a.status ? attBadgeVariant(a.status) : 'neutral'">
                    {{ (a.status ? attendanceKey(a.status) : 'meetings.attendance.unknown') | t }}
                  </app-badge>
                }
              </li>
            }
          </ul>
        </app-card>
      }
    } @else {
      <!-- Übersicht: vorhandene Sitzungen (#104) als geteilte Tabelle (#27) -->
      @if (canManage() || canWrite()) {
        <section class="mtg__listSection">
          <header class="mtg__listHead">
            <h2 class="mtg__listH">{{ 'meetings.list.title' | t }}</h2>
            <!-- Anlegen nur für Sitzungsleitung (#35) — über Dialog (#27). -->
            @if (canManage()) {
              <app-button size="sm" (click)="openCreate()">{{ 'meetings.list.new' | t }}</app-button>
            }
          </header>
          @if (loadingList()) {
            <p class="mtg__muted" aria-live="polite">{{ 'meetings.list.loading' | t }}</p>
          } @else {
            <app-data-table
              [columns]="listColumns()"
              [rows]="meetings()"
              [emptyText]="'meetings.list.empty' | t"
              [clickable]="true"
              (rowClick)="openMeeting($any($event).id)"
            >
              <ng-template appCell="date" let-m>
                @if ($any(m).date) {
                  <span class="mtg__muted">{{ $any(m).date | date: 'mediumDate' }}{{ $any(m).startTime ? ', ' + $any(m).startTime : '' }}</span>
                } @else { — }
              </ng-template>
              <ng-template appCell="status" let-m>
                <app-badge [variant]="statusVariant($any(m).status)">{{ statusKey($any(m).status) | t }}</app-badge>
              </ng-template>
              <ng-template appCell="actions" let-m>
                <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'meetings.list.open' | t" (click)="$event.stopPropagation(); openMeeting($any(m).id)">
                  <app-icon name="chevron-down" class="mtg__openIcon" />
                </app-button>
              </ng-template>
            </app-data-table>
          }
        </section>
      } @else {
        <p class="mtg__status">{{ 'meetings.empty' | t }}</p>
      }

      <!-- Anlegen (nur Sitzungsleitung) als Dialog (#27/#19) -->
      <app-dialog
        [open]="createOpen()"
        [title]="'meetings.create.title' | t"
        [closeLabel]="'action.cancel' | t"
        (closed)="createOpen.set(false)"
      >
        <form id="mtg-create" class="mtg__createForm" (submit)="create($event)">
          <label class="mtg__paneLabel" [for]="'mtg-new'">{{ 'meetings.create.name' | t }}</label>
          <input
            id="mtg-new"
            class="mtg__input"
            [placeholder]="'meetings.create.placeholder' | t"
            [ngModel]="newTitle()"
            (ngModelChange)="newTitle.set($event)"
            name="title"
          />
          <app-select
            name="gremium"
            [label]="'meetings.create.gremium' | t"
            [placeholder]="'meetings.create.gremiumPlaceholder' | t"
            [options]="gremiumOptions()"
            [required]="true"
            [ngModel]="newGremiumId()"
            (ngModelChange)="newGremiumId.set($event)"
          />
          @if (!gremiumOptions().length) {
            <p class="mtg__muted mtg__hint">{{ 'meetings.create.noGremien' | t }}</p>
          }
          <app-datepicker
            [label]="'meetings.create.date' | t"
            [ngModel]="newDate()"
            (ngModelChange)="newDate.set($event)"
            name="date"
          />
          <label class="mtg__paneLabel" for="mtg-new-time">{{ 'meetings.create.time' | t }}</label>
          <input
            id="mtg-new-time"
            class="mtg__input"
            type="time"
            [ngModel]="newTime()"
            (ngModelChange)="newTime.set($event)"
            name="time"
          />
        </form>
        <div dialog-footer class="mtg__dialogFoot">
          <app-button variant="ghost" (click)="createOpen.set(false)">{{ 'action.cancel' | t }}</app-button>
          <app-button
            [disabled]="!newTitle().trim() || !newGremiumId()"
            [loading]="creating()"
            (click)="create($event)"
          >
            {{ 'meetings.create.submit' | t }}
          </app-button>
        </div>
      </app-dialog>
    }
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .mtg__head {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .mtg__meta {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        flex-wrap: wrap;
      }
      .mtg__name {
        font-weight: var(--fw-semibold);
      }
      .mtg__status {
        color: var(--color-text-muted);
        padding: var(--space-5) 0;
      }
      .mtg__status--error {
        color: var(--color-danger);
      }
      .mtg__lead {
        color: var(--color-text-muted);
        margin: 0 0 var(--space-3);
      }
      .mtg__listSection {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .mtg__listHead {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
      }
      .mtg__listH {
        margin: 0;
        font-size: var(--fs-lg);
      }
      .mtg__openIcon {
        transform: rotate(-90deg);
      }
      .mtg__dialogFoot {
        display: flex;
        justify-content: flex-end;
        gap: var(--space-3);
      }
      .mtg__muted {
        color: var(--color-text-muted);
      }
      .mtg__hint {
        font-size: var(--fs-sm);
        align-self: center;
      }
      .mtg__statusActions {
        display: flex;
        gap: var(--space-2);
        margin-bottom: var(--space-4);
        flex-wrap: wrap;
      }
      .mtg__votes {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .mtg__vote {
        padding: var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .mtg__vote--active {
        border-color: var(--color-primary);
        background: var(--color-primary-subtle);
      }
      .mtg__voteHead {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
      }
      .mtg__voteTitle {
        font-weight: var(--fw-medium);
        margin-right: auto;
      }
      .mtg__tally {
        display: flex;
        gap: var(--space-4);
        margin: 0;
        flex-wrap: wrap;
      }
      .mtg__tally > div {
        display: flex;
        gap: var(--space-2);
        font-size: var(--fs-sm);
        color: var(--color-text-muted);
      }
      .mtg__tally > div dt::after {
        content: ':';
      }
      .mtg__tally > div dd {
        margin: 0;
        font-weight: var(--fw-semibold);
        color: var(--color-text);
      }
      .mtg__tally--leading dd {
        color: var(--color-primary);
      }
      .mtg__voteActions {
        display: flex;
        gap: var(--space-2);
        flex-wrap: wrap;
      }
      .mtg__protoMeta {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        margin-bottom: var(--space-3);
      }
      .mtg__pdf {
        color: var(--color-primary);
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
      }
      .mtg__snippets {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--space-2);
        margin-bottom: var(--space-3);
      }
      .mtg__snippetsLabel {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text-muted);
      }
      .mtg__editor {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--space-4);
      }
      @media (max-width: 48rem) {
        .mtg__editor {
          grid-template-columns: 1fr;
        }
      }
      .mtg__pane {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        min-width: 0;
      }
      .mtg__paneLabel {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text-muted);
      }
      .mtg__textarea,
      .mtg__input {
        padding: var(--space-3) var(--space-4);
        background: var(--color-surface);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
        font-family: inherit;
      }
      .mtg__textarea {
        resize: vertical;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        line-height: 1.5;
      }
      .mtg__textarea:focus-visible,
      .mtg__input:focus-visible {
        outline: 2px solid var(--color-primary);
        outline-offset: 1px;
      }
      .mtg__preview {
        padding: var(--space-3) var(--space-4);
        background: var(--color-surface-sunken);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        overflow-wrap: anywhere;
        min-height: 8rem;
      }
      .mtg__preview :first-child {
        margin-top: 0;
      }
      .mtg__preview blockquote {
        margin: var(--space-2) 0;
        padding-left: var(--space-3);
        border-left: 3px solid var(--color-border-strong);
        color: var(--color-text-muted);
      }
      .mtg__preview code {
        background: var(--color-bg);
        padding: 0 var(--space-1);
        border-radius: var(--radius-sm);
        font-size: 0.9em;
      }
      .mtg__preview a {
        color: var(--color-primary);
        text-decoration: underline;
      }
      .mtg__preview ul,
      .mtg__preview ol {
        margin: var(--space-2) 0;
        padding-left: var(--space-5);
      }
      .mtg__preview hr {
        border: 0;
        border-top: var(--border-width) solid var(--color-border);
        margin: var(--space-3) 0;
      }
      .mtg__preview table {
        border-collapse: collapse;
        width: 100%;
        margin: var(--space-2) 0;
        font-size: var(--fs-sm);
      }
      .mtg__preview th,
      .mtg__preview td {
        border: var(--border-width) solid var(--color-border);
        padding: var(--space-1) var(--space-2);
        text-align: start;
      }
      .mtg__preview thead th {
        background: var(--color-surface);
        font-weight: var(--fw-semibold);
      }
      .mtg__protoActions {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        margin-top: var(--space-4);
        flex-wrap: wrap;
      }
      .mtg__saveState {
        font-size: var(--fs-sm);
        color: var(--color-text-muted);
        min-width: 8rem;
      }
      .mtg__saveState[data-state='saved'] {
        color: var(--color-success);
      }
      .mtg__saveState[data-state='error'] {
        color: var(--color-danger);
      }
      .mtg__att {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .mtg__attRow {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-3);
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        flex-wrap: wrap;
      }
      .mtg__attName {
        font-weight: var(--fw-medium);
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
      }
      .mtg__attYou {
        font-size: var(--fs-xs);
        font-weight: var(--fw-normal);
        color: var(--color-text-muted);
      }
      .mtg__attBtns {
        display: inline-flex;
        gap: var(--space-1);
        flex-wrap: wrap;
      }
      .mtg__createForm {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        max-width: 28rem;
      }
      .mtg__planRow {
        display: flex;
        align-items: end;
        gap: var(--space-3);
        flex-wrap: wrap;
      }
      .mtg__list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .mtg__listItem {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        padding: var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
      }
      .mtg__listTitle {
        font-weight: var(--fw-medium);
        margin-right: auto;
      }
    `,
  ],
})
export class MeetingsComponent implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly ws = inject(WsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly useMock = inject(USE_MOCK_API);
  private readonly options = inject(AdminOptionsService);

  readonly loading = signal(false);
  readonly error = signal(false);
  readonly meeting = signal<Meeting | null>(null);
  readonly protocol = signal<Protocol | null>(null);

  /** Anwesenheits-Roster der Sitzung (#Meetings/#55/#56). */
  readonly attendance = signal<Attendance[]>([]);
  readonly savingAttendance = signal(false);
  readonly attendanceStatuses: readonly AttendanceStatus[] = ['present', 'excused', 'absent'];

  /** Sitzungs-Liste (#104) — gezeigt, solange keine einzelne Sitzung geladen ist. */
  readonly meetings = signal<Meeting[]>([]);
  readonly loadingList = signal(false);

  readonly markdown = signal('');
  readonly dirty = signal(false);
  private caret: number | null = null;

  readonly loadingProtocol = signal(false);
  readonly saving = signal(false);
  /** Auto-Speichern-Status des Protokolls (#56). */
  readonly saveState = signal<'idle' | 'saving' | 'saved' | 'error'>('idle');
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  readonly finalizing = signal(false);
  readonly creating = signal(false);
  readonly newTitle = signal('');
  /** Optionales geplantes Datum für die neue Sitzung (#7), `YYYY-MM-DD`. */
  readonly newDate = signal('');
  /** Optionale geplante Uhrzeit (#34), `HH:mm`. */
  readonly newTime = signal('');
  /** Datums-/Zeit-Editor einer bereits angelegten, geplanten Sitzung (#7/#34). */
  readonly planDate = signal('');
  readonly planTime = signal('');
  readonly savingDate = signal(false);
  /** Pflicht-Gremium für die neue Sitzung (#68); leer ⇒ Submit gesperrt. */
  readonly newGremiumId = signal('');
  /** Gremien als Dropdown-Optionen (echte Liste, `/gremien`). */
  readonly gremiumOptions = signal<SelectOption[]>([]);
  /** Sitzung-anlegen-Dialog offen (#27). */
  readonly createOpen = signal(false);

  /** Spalten der Sitzungs-Übersichtstabelle (#27). */
  readonly listColumns = computed<ColumnDef[]>(() => [
    { key: 'title', label: this.i18n.translate('meetings.create.name') },
    { key: 'date', label: this.i18n.translate('meetings.create.date') },
    { key: 'status', label: this.i18n.translate('meetings.list.status'), align: 'start', width: '9rem' },
    { key: 'actions', label: '', align: 'end', width: '4rem' },
  ]);

  openCreate(): void {
    this.createOpen.set(true);
  }

  readonly canManage = computed(() => this.auth.can('meeting.manage'));
  readonly canWrite = computed(() => this.auth.can('protocol.write'));
  readonly previewHtml = computed(() => renderMarkdown(this.markdown()));

  private channel: MeetingChannel | null = null;

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      const id = pm.get('id');
      if (id) {
        this.loadMeeting(id);
      } else {
        // Übersichts-Route `/meetings`: einzelne Sitzung lösen + Liste laden (#104).
        this.meeting.set(null);
        this.loadList();
      }
    });
    // Gremien-Liste für das Anlege-Dropdown (#68) — nur wer Sitzungen verwaltet.
    if (this.canManage()) {
      this.options
        .gremiumOptions()
        .pipe(takeUntilDestroyed())
        .subscribe({
          next: (opts) => this.gremiumOptions.set(opts),
          error: () => this.gremiumOptions.set([]),
        });
    }
  }

  ngOnDestroy(): void {
    this.channel?.close();
    if (this.saveTimer !== null) clearTimeout(this.saveTimer);
  }

  // --- laden / anlegen -----------------------------------------------------
  private loadMeeting(id: Uuid): void {
    this.loading.set(true);
    this.error.set(false);
    this.api.getMeeting(id).subscribe({
      next: (m) => {
        this.loading.set(false);
        this.adoptMeeting(m);
      },
      error: () => {
        this.loading.set(false);
        this.error.set(true);
      },
    });
  }

  private adoptMeeting(m: Meeting): void {
    this.meeting.set(m);
    this.planDate.set(m.date ?? '');
    this.planTime.set(m.startTime ?? '');
    this.connectLive(m.id);
    if (m.protocolId && this.canWrite()) this.loadProtocol();
    this.loadAttendance(m.id);
  }

  /** Sitzungs-Liste laden (#104 — Wiederauffindbarkeit). */
  private loadList(): void {
    if (!this.canManage() && !this.canWrite()) return;
    this.loadingList.set(true);
    this.api.listMeetings().subscribe({
      next: (list) => {
        this.loadingList.set(false);
        this.meetings.set(list);
      },
      error: () => {
        this.loadingList.set(false);
        this.meetings.set([]);
      },
    });
  }

  create(event: Event): void {
    event.preventDefault();
    const title = this.newTitle().trim();
    const gremiumId = this.newGremiumId();
    if (!title || !gremiumId || this.creating()) return;
    this.creating.set(true);
    const date = this.newDate().trim() || null;
    const startTime = this.newTime().trim() || null;
    this.api.createMeeting({ title, gremiumId, date, startTime }).subscribe({
      next: (m) => {
        this.creating.set(false);
        this.newTitle.set('');
        this.newGremiumId.set('');
        this.newDate.set('');
        this.newTime.set('');
        this.createOpen.set(false);
        this.toast.success(this.i18n.translate('meetings.toast.created'));
        // Auf die Detail-Route navigieren, damit die Sitzung wiederauffindbar ist (#104).
        void this.router.navigate(['/meetings', m.id]);
      },
      error: () => {
        this.creating.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.createFailed'));
      },
    });
  }

  /** Eine Sitzung aus der Liste öffnen → Detail-Route (#104). */
  openMeeting(id: Uuid): void {
    void this.router.navigate(['/meetings', id]);
  }

  // --- Sitzungssteuerung ---------------------------------------------------
  setStatus(status: 'live' | 'closed'): void {
    const m = this.meeting();
    if (!m) return;
    this.api.patchMeeting(m.id, { status }).subscribe({
      next: (updated) => this.meeting.set(updated),
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  /** Geplantes Datum einer (geplanten) Sitzung vorab setzen (#7, PATCH date). */
  savePlannedDate(): void {
    const m = this.meeting();
    const date = this.planDate().trim();
    if (!m || !date || this.savingDate()) return;
    this.savingDate.set(true);
    this.api.patchMeeting(m.id, { date, startTime: this.planTime().trim() || null }).subscribe({
      next: (updated) => {
        this.savingDate.set(false);
        this.meeting.set(updated);
        this.toast.success(this.i18n.translate('meetings.toast.dateSaved'));
      },
      error: () => {
        this.savingDate.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  setActive(applicationId: Uuid): void {
    const m = this.meeting();
    if (!m) return;
    this.api.patchMeeting(m.id, { activeApplicationId: applicationId }).subscribe({
      next: (updated) => this.meeting.set(updated),
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  openVote(voteId: Uuid): void {
    this.api.openVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'open' }),
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  closeVote(voteId: Uuid): void {
    this.api.closeVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'closed' }),
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  // --- Protokoll-Editor ----------------------------------------------------
  loadProtocol(): void {
    const m = this.meeting();
    if (!m || this.loadingProtocol()) return;
    this.loadingProtocol.set(true);
    this.api.loadProtocol(m.id).subscribe({
      next: (proto) => {
        this.loadingProtocol.set(false);
        this.protocol.set(proto);
        this.markdown.set(proto.markdown);
        this.dirty.set(false);
      },
      error: () => {
        this.loadingProtocol.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.protocolFailed'));
      },
    });
  }

  onMarkdownChange(value: string): void {
    this.markdown.set(value);
    this.dirty.set(true);
    this.scheduleAutosave();
  }

  onCaret(event: Event): void {
    const target = event.target as HTMLTextAreaElement;
    this.caret = typeof target.selectionStart === 'number' ? target.selectionStart : null;
  }

  insertAntrag(vote: MeetingVote): void {
    this.insertSnippet(antragSnippet(vote.applicationId, vote.title));
  }

  insertVote(vote: MeetingVote): void {
    this.insertSnippet(voteSnippet(vote));
  }

  private insertSnippet(snippet: string): void {
    const next = insertAt(this.markdown(), snippet, this.caret);
    this.markdown.set(next);
    this.dirty.set(true);
    this.scheduleAutosave();
  }

  /** Debounced Auto-Speichern (#56): nach kurzer Tipp-Pause an den Server. */
  private scheduleAutosave(): void {
    if (this.saveTimer !== null) clearTimeout(this.saveTimer);
    this.saveState.set('idle');
    this.saveTimer = setTimeout(() => {
      this.saveTimer = null;
      this.autosave();
    }, AUTOSAVE_DELAY_MS);
  }

  private autosave(): void {
    const proto = this.protocol();
    if (!proto || proto.isFinal || !this.dirty() || this.saving()) return;
    const pending = this.markdown();
    this.saving.set(true);
    this.saveState.set('saving');
    this.api.updateProtocol(proto.id, pending).subscribe({
      next: (updated) => {
        this.saving.set(false);
        this.protocol.set(updated);
        // Nur als gespeichert markieren, wenn der Editor seither nicht weiter
        // verändert wurde (sonst läuft bereits der nächste Autosave-Timer).
        if (this.markdown() === pending) {
          this.dirty.set(false);
          this.saveState.set('saved');
        }
      },
      error: () => {
        this.saving.set(false);
        this.saveState.set('error');
      },
    });
  }

  finalize(): void {
    const proto = this.protocol();
    if (!proto || this.finalizing() || this.dirty()) return;
    this.finalizing.set(true);
    this.api.finalizeProtocol(proto.id).subscribe({
      next: (updated) => {
        this.finalizing.set(false);
        this.protocol.set(updated);
        this.toast.success(this.i18n.translate('meetings.toast.finalized'));
      },
      error: (err: unknown) => {
        this.finalizing.set(false);
        // Render-/Compile-Fehler (400) tragen einen konkreten Grund — anzeigen.
        const detail = this.errorDetail(err);
        this.toast.error(
          detail
            ? `${this.i18n.translate('meetings.toast.finalizeFailed')}: ${detail}`
            : this.i18n.translate('meetings.toast.finalizeFailed'),
        );
      },
    });
  }

  /** Konkrete `problem+json`-`detail`-Meldung aus einem HTTP-Fehler (oder leer). */
  private errorDetail(err: unknown): string {
    const body = (err as { error?: { detail?: string } } | null)?.error;
    return typeof body?.detail === 'string' ? body.detail : '';
  }

  // --- Anwesenheit (#Meetings/#55/#56) -------------------------------------
  private loadAttendance(meetingId: Uuid): void {
    this.api.listAttendance(meetingId).subscribe({
      next: (rows) => this.attendance.set(rows),
      error: () => this.attendance.set([]),
    });
  }

  setAttendance(member: Attendance, status: AttendanceStatus): void {
    const m = this.meeting();
    if (!m || this.savingAttendance() || member.status === status) return;
    this.savingAttendance.set(true);
    // Eigene Anwesenheit als »self« markieren; Mitglieder setzt die Leitung.
    const req = member.isSelf
      ? this.api.setOwnAttendance(m.id, status)
      : this.api.setMemberAttendance(m.id, member.principalId, status);
    req.subscribe({
      next: (rows) => {
        this.savingAttendance.set(false);
        this.attendance.set(rows);
      },
      error: () => {
        this.savingAttendance.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  attendanceKey(status: AttendanceStatus | 'unknown'): TranslationKey {
    return `meetings.attendance.${status}` as TranslationKey;
  }

  attBtnVariant(status: AttendanceStatus): 'primary' | 'secondary' | 'danger' {
    return status === 'present' ? 'primary' : status === 'excused' ? 'secondary' : 'danger';
  }

  attBadgeVariant(status: AttendanceStatus): BadgeVariant {
    return status === 'present' ? 'success' : status === 'excused' ? 'warning' : 'danger';
  }

  // --- Live (WebSocket) ----------------------------------------------------
  private connectLive(meetingId: Uuid): void {
    // Im Mock-Betrieb (FE-Dev/Harness) gibt es keinen WS-Server → kein Live-Kanal,
    // sonst scheitert der Handshake und verrauscht die Konsole.
    if (this.useMock) return;
    this.channel?.close();
    this.channel = this.ws.connectMeeting(meetingId);
    this.channel.messages$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => this.onLive(msg));
  }

  private onLive(msg: ServerMessage): void {
    const m = this.meeting();
    if (!m) return;
    switch (msg.type) {
      case 'meeting_state':
        this.meeting.set({
          ...m,
          status: (msg.status as Meeting['status']) ?? m.status,
          activeApplicationId: msg.activeApplicationId,
        });
        break;
      case 'vote_opened':
        this.patchVote(msg.voteId, { status: 'open', closesAt: msg.closesAt });
        break;
      case 'vote_tally':
        this.patchVote(msg.voteId, { counts: msg.counts, leading: msg.leading });
        break;
      case 'vote_closed':
        this.patchVote(msg.voteId, { status: 'closed', result: msg.result, counts: msg.counts });
        break;
      default:
        break;
    }
  }

  /** Ein einzelnes Vote im Sitzungs-State immutabel patchen. */
  private patchVote(voteId: Uuid, patch: Partial<MeetingVote>): void {
    const m = this.meeting();
    if (!m) return;
    this.meeting.set({
      ...m,
      votes: m.votes.map((v) => (v.id === voteId ? { ...v, ...patch } : v)),
    });
  }

  // --- Anzeige-Helfer ------------------------------------------------------
  statusVariant(status: Meeting['status']): BadgeVariant {
    return status === 'live' ? 'success' : status === 'closed' ? 'neutral' : 'info';
  }

  voteVariant(status: MeetingVote['status']): BadgeVariant {
    return status === 'open' ? 'success' : status === 'closed' ? 'neutral' : 'warning';
  }

  /** Typsichere i18n-Keys aus dem dynamischen Status (strictTemplates). */
  statusKey(status: Meeting['status']): TranslationKey {
    return `meetings.status.${status}` as TranslationKey;
  }

  voteStatusKey(status: MeetingVote['status']): TranslationKey {
    return `meetings.voteStatus.${status}` as TranslationKey;
  }

  countEntries(vote: MeetingVote): { key: string; value: number }[] {
    return Object.entries(vote.counts ?? {}).map(([key, value]) => ({ key, value }));
  }
}
