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
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  AgendaItem,
  AssignableApplication,
  Attendance,
  AttendanceStatus,
  I18nMap,
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
  MarkdownEditorComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminOptionsService } from '../../pages/admin/admin-options.service';

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
    RouterLink,
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
    MarkdownEditorComponent,
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
                    <span class="mtg__voteTitle">{{ vote.question || vote.title || vote.applicationId }}</span>
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

      <!-- Abstimmung für einen Antrag öffnen (Live-Vote mit Beschlussfrage, #Meetings) -->
      <app-dialog
        [open]="voteDialogOpen()"
        [title]="'meetings.vote.dialogTitle' | t"
        [closeLabel]="'action.cancel' | t"
        (closed)="closeVoteDialog()"
      >
        <form class="mtg__voteForm" (submit)="$event.preventDefault(); submitVote()">
          <label class="mtg__paneLabel" for="mtg-vq">{{ 'meetings.vote.question' | t }}</label>
          <input
            id="mtg-vq"
            class="mtg__input"
            [ngModel]="voteQuestion()"
            (ngModelChange)="voteQuestion.set($event)"
            name="vq"
            [placeholder]="'meetings.vote.questionPlaceholder' | t"
          />
          <label class="mtg__paneLabel" for="mtg-vo">{{ 'meetings.vote.options' | t }}</label>
          <textarea
            id="mtg-vo"
            class="mtg__textarea"
            rows="4"
            [ngModel]="voteOptions()"
            (ngModelChange)="voteOptions.set($event)"
            name="vo"
          ></textarea>
          <label class="mtg__voteSecret">
            <input type="checkbox" [checked]="voteSecret()" (change)="voteSecret.set($any($event.target).checked)" />
            {{ 'meetings.vote.secret' | t }}
          </label>
        </form>
        <div dialog-footer class="mtg__dialogFoot">
          <app-button variant="ghost" (click)="closeVoteDialog()">{{ 'action.cancel' | t }}</app-button>
          <app-button [disabled]="voteOptionList().length < 2 || openingVote()" [loading]="openingVote()" (click)="submitVote()">
            {{ 'meetings.vote.openSubmit' | t }}
          </app-button>
        </div>
      </app-dialog>

      <!-- Protokoll & Tagesordnung: TOPs links (sortierbar), pro-TOP-Editor rechts (#58) -->
      @if (canWrite() || canManage()) {
        <app-card [heading]="'meetings.protocol.title' | t">
          @if (!protocol()) {
            <p class="mtg__muted">{{ 'meetings.protocol.none' | t }}</p>
            @if (canWrite()) {
              <app-button size="sm" [loading]="loadingProtocol()" (click)="loadProtocol()">
                {{ 'meetings.protocol.create' | t }}
              </app-button>
            }
          } @else if (protocol(); as proto) {
            <div class="mtg__protoMeta">
              <app-badge [variant]="proto.isFinal ? 'success' : 'neutral'">
                {{ (proto.isFinal ? 'meetings.protocol.final' : 'meetings.protocol.draft') | t }}
              </app-badge>
              @if (proto.pdfUrl) {
                <a class="mtg__pdf" [href]="proto.pdfUrl" target="_blank" rel="noopener">{{ 'meetings.protocol.pdf' | t }}</a>
              }
              <span class="mtg__saveState" [attr.data-state]="saveState()" aria-live="polite">
                @switch (saveState()) {
                  @case ('saving') { {{ 'meetings.protocol.saving' | t }} }
                  @case ('saved') { ✓ {{ 'meetings.protocol.saved' | t }} }
                  @case ('error') { {{ 'meetings.protocol.saveFailed' | t }} }
                  @default {}
                }
              </span>
            </div>

            <div class="mtg__tops">
              <!-- Links: TOP-Inhaltsverzeichnis (drag-sortierbar) -->
              <aside class="mtg__toc" [attr.aria-label]="'meetings.agenda.title' | t">
                <ol class="mtg__tocList">
                  @for (item of agenda(); track item.id; let i = $index) {
                    <li
                      class="mtg__tocItem"
                      [class.mtg__tocItem--sel]="selectedTopId() === item.id"
                      [attr.draggable]="m.canControl && !proto.isFinal"
                      (dragstart)="onTopDragStart(i)"
                      (dragover)="onTopDragOver($event)"
                      (drop)="onTopDrop(i)"
                      (click)="selectTop(item.id)"
                    >
                      @if (m.canControl && !proto.isFinal) {
                        <span class="mtg__tocGrip" aria-hidden="true">⠿</span>
                      }
                      <span class="mtg__tocNum">{{ i + 1 }}</span>
                      <span class="mtg__tocTitle">{{ item.title || ('meetings.agenda.untitled' | t) }}</span>
                      @if (m.canControl && item.applicationId) {
                        <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'meetings.vote.openFor' | t" [attr.title]="'meetings.vote.openFor' | t" (click)="$event.stopPropagation(); openVoteDialog(item)"><app-icon name="roles" /></app-button>
                      }
                      @if (m.canControl && !proto.isFinal) {
                        <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.remove' | t" [disabled]="savingAgenda()" (click)="$event.stopPropagation(); removeFromAgenda(item.id)"><app-icon name="delete" /></app-button>
                      }
                    </li>
                  } @empty {
                    <li class="mtg__muted mtg__tocEmpty">{{ 'meetings.agenda.empty' | t }}</li>
                  }
                </ol>
                @if (m.canControl && !proto.isFinal) {
                  <div class="mtg__tocAdd">
                    <app-select [placeholder]="'meetings.agenda.addPlaceholder' | t" [options]="assignableOptions()" [ngModel]="agendaPick()" (ngModelChange)="agendaPick.set($event)" />
                    <app-button size="sm" [disabled]="!agendaPick() || savingAgenda()" (click)="addToAgenda()">{{ 'meetings.agenda.add' | t }}</app-button>
                  </div>
                  <div class="mtg__tocAdd">
                    <input class="mtg__input" [placeholder]="'meetings.agenda.freetextPlaceholder' | t" [ngModel]="agendaFreetext()" (ngModelChange)="agendaFreetext.set($event)" (keyup.enter)="addFreetext()" name="agendaFreetext" />
                    <app-button variant="secondary" size="sm" [disabled]="!agendaFreetext().trim() || savingAgenda()" (click)="addFreetext()">{{ 'meetings.agenda.addFreetext' | t }}</app-button>
                  </div>
                }
              </aside>

              <!-- Rechts: Markdown-Editor des gewählten TOP (WYSIWYG, kein separater Preview) -->
              <div class="mtg__topEditor">
                @if (selectedTop(); as top) {
                  <div class="mtg__topHead">
                    <h3 class="mtg__topTitle">{{ 'meetings.agenda.top' | t: { n: selectedIndex() + 1 } }}: {{ top.title || ('meetings.agenda.untitled' | t) }}</h3>
                    @if (top.applicationId) {
                      <a class="mtg__pdf" [routerLink]="['/applications', top.applicationId]">{{ 'meetings.agenda.openApplication' | t }}</a>
                    }
                  </div>
                  <app-markdown-editor
                    [docKey]="top.id"
                    [value]="top.body ?? ''"
                    [disabled]="proto.isFinal || !m.canControl"
                    [placeholder]="'meetings.protocol.placeholder' | t"
                    (valueChange)="onTopBodyChange(top.id, $event)"
                  />
                } @else {
                  <p class="mtg__muted mtg__topEmpty">{{ 'meetings.protocol.selectTop' | t }}</p>
                }
              </div>
            </div>

            <div class="mtg__protoActions">
              @if (!proto.isFinal) {
                @if (canWrite()) {
                  <app-button variant="primary" size="sm" [disabled]="savingTop() || !agenda().length" [loading]="finalizing()" (click)="finalize()">
                    {{ 'meetings.protocol.finalize' | t }}
                  </app-button>
                  @if (savingTop()) { <span class="mtg__muted mtg__hint">{{ 'meetings.protocol.saving' | t }}</span> }
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
      .mtg__preview .callout {
        margin: var(--space-2) 0;
        padding: var(--space-2) var(--space-3);
        border-left: 4px solid var(--callout-color, var(--color-border-strong));
        border-radius: var(--radius-sm);
        background: color-mix(in srgb, var(--callout-color, var(--color-border-strong)) 8%, transparent);
      }
      .mtg__preview .callout :last-child {
        margin-bottom: 0;
      }
      .mtg__preview .callout__title {
        font-weight: var(--fw-semibold);
        color: var(--callout-color, var(--color-text));
        margin: 0 0 var(--space-1);
      }
      .mtg__preview .callout--note { --callout-color: #1f6feb; }
      .mtg__preview .callout--tip { --callout-color: #1a7f37; }
      .mtg__preview .callout--important { --callout-color: #8250df; }
      .mtg__preview .callout--warning { --callout-color: #9a6700; }
      .mtg__preview .callout--caution { --callout-color: #cf222e; }
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
      .mtg__tops {
        display: grid;
        grid-template-columns: minmax(0, 18rem) minmax(0, 1fr);
        gap: var(--space-4);
        align-items: start;
      }
      @media (max-width: 52rem) {
        .mtg__tops {
          grid-template-columns: 1fr;
        }
      }
      .mtg__toc {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .mtg__tocList {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      .mtg__tocItem {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        padding: var(--space-2);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        cursor: pointer;
      }
      .mtg__tocItem:hover {
        background: var(--color-surface-sunken);
      }
      .mtg__tocItem--sel {
        border-color: var(--color-primary);
        background: var(--color-primary-subtle);
      }
      .mtg__tocGrip {
        cursor: grab;
        color: var(--color-text-muted);
      }
      .mtg__tocNum {
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .mtg__tocTitle {
        flex: 1;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: var(--fs-sm);
      }
      .mtg__tocEmpty {
        padding: var(--space-2);
      }
      .mtg__tocAdd {
        display: flex;
        gap: var(--space-2);
        align-items: center;
      }
      .mtg__topEditor {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        min-width: 0;
      }
      .mtg__topHead {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--space-3);
        flex-wrap: wrap;
      }
      .mtg__topTitle {
        margin: 0;
        font-size: var(--fs-md);
      }
      .mtg__topEmpty {
        padding: var(--space-5) 0;
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
      .mtg__agendaAdd {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        margin-bottom: var(--space-3);
        flex-wrap: wrap;
      }
      .mtg__agenda {
        margin: 0;
        padding: 0;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .mtg__agendaRow {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        flex-wrap: wrap;
      }
      .mtg__agendaTop {
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
        white-space: nowrap;
      }
      .mtg__agendaTitle {
        font-weight: var(--fw-medium);
        color: var(--color-text);
        text-decoration: none;
        margin-right: auto;
      }
      .mtg__agendaTitle:hover {
        color: var(--color-primary);
        text-decoration: underline;
      }
      .mtg__voteForm {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        max-width: 30rem;
      }
      .mtg__voteSecret {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
        font-size: var(--fs-sm);
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

  /** Tagesordnung + zuweisbare Abstimmungs-Anträge (#10/#58). */
  readonly agenda = signal<AgendaItem[]>([]);
  readonly assignable = signal<AssignableApplication[]>([]);
  readonly savingAgenda = signal(false);
  readonly agendaPick = signal<string>('');
  readonly agendaFreetext = signal<string>('');

  /** Live-Abstimmung öffnen (#Meetings): Dialog-Zustand + Beschlussfrage/Optionen. */
  readonly voteDialogOpen = signal(false);
  private readonly voteItem = signal<AgendaItem | null>(null);
  readonly voteQuestion = signal<string>('');
  readonly voteOptions = signal<string>('Ja\nNein\nEnthaltung');
  readonly voteSecret = signal(false);
  readonly openingVote = signal(false);
  readonly voteOptionList = computed(() =>
    this.voteOptions()
      .split(/[\n,]/)
      .map((o) => o.trim())
      .filter((o) => o.length > 0),
  );
  readonly assignableOptions = computed<SelectOption[]>(() =>
    this.assignable().map((a) => ({ value: a.applicationId, label: a.title || a.applicationId })),
  );

  /** Sitzungs-Liste (#104) — gezeigt, solange keine einzelne Sitzung geladen ist. */
  readonly meetings = signal<Meeting[]>([]);
  readonly loadingList = signal(false);

  readonly loadingProtocol = signal(false);
  readonly saving = signal(false);
  /** Auto-Speichern-Status des aktuellen TOP-Texts (#56/#58). */
  readonly saveState = signal<'idle' | 'saving' | 'saved' | 'error'>('idle');
  /** Aktuell im rechten Editor gewählter TOP. */
  readonly selectedTopId = signal<Uuid | null>(null);
  readonly savingTop = signal(false);
  private bodyTimer: ReturnType<typeof setTimeout> | null = null;
  private dragTopIndex: number | null = null;
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

  /** Aktuell gewählter TOP (rechter Editor) + sein 0-basierter Index. */
  readonly selectedTop = computed<AgendaItem | null>(
    () => this.agenda().find((a) => a.id === this.selectedTopId()) ?? null,
  );
  readonly selectedIndex = computed(() =>
    this.agenda().findIndex((a) => a.id === this.selectedTopId()),
  );

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
    if (this.bodyTimer !== null) clearTimeout(this.bodyTimer);
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
    this.loadAgenda(m.id);
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

  // --- Protokoll: TOPs links, pro-TOP-Editor rechts (#58) ------------------
  loadProtocol(): void {
    const m = this.meeting();
    if (!m || this.loadingProtocol()) return;
    this.loadingProtocol.set(true);
    this.api.loadProtocol(m.id).subscribe({
      next: (proto) => {
        this.loadingProtocol.set(false);
        this.protocol.set(proto);
      },
      error: () => {
        this.loadingProtocol.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.protocolFailed'));
      },
    });
  }

  selectTop(id: Uuid): void {
    this.selectedTopId.set(id);
  }

  /** Markdown-Text eines TOP debounced an den Server (PATCH …/agenda/{id}). */
  onTopBodyChange(itemId: Uuid, body: string): void {
    const m = this.meeting();
    if (!m) return;
    if (this.bodyTimer !== null) clearTimeout(this.bodyTimer);
    this.saveState.set('idle');
    this.bodyTimer = setTimeout(() => {
      this.bodyTimer = null;
      this.savingTop.set(true);
      this.saveState.set('saving');
      this.api.setAgendaBody(m.id, itemId, body).subscribe({
        next: (rows) => {
          this.savingTop.set(false);
          this.agenda.set(rows);
          this.saveState.set('saved');
        },
        error: () => {
          this.savingTop.set(false);
          this.saveState.set('error');
        },
      });
    }, AUTOSAVE_DELAY_MS);
  }

  // --- TOP-Reihenfolge (Drag&Drop) -----------------------------------------
  onTopDragStart(index: number): void {
    this.dragTopIndex = index;
  }

  onTopDragOver(event: DragEvent): void {
    if (this.dragTopIndex !== null) event.preventDefault();
  }

  onTopDrop(index: number): void {
    const from = this.dragTopIndex;
    this.dragTopIndex = null;
    const m = this.meeting();
    if (from === null || from === index || !m) return;
    const items = [...this.agenda()];
    const [moved] = items.splice(from, 1);
    items.splice(index, 0, moved);
    this.agenda.set(items); // optimistisch
    this.api.reorderAgenda(m.id, items.map((i) => i.id)).subscribe({
      next: (rows) => this.agenda.set(rows),
      error: () => {
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
        if (m) this.loadAgenda(m.id);
      },
    });
  }

  /** Protokoll-Markdown aus den geordneten TOPs zusammensetzen (#58). */
  private assembleMarkdown(): string {
    return this.agenda()
      .map((t, i) => {
        const heading = `## TOP ${i + 1}: ${t.title ?? ''}`.trimEnd();
        const ref = t.applicationId ? `\n\n:::antrag{#${t.applicationId}}\n:::` : '';
        const body = t.body?.trim() ? `\n\n${t.body.trim()}` : '';
        return `${heading}${ref}${body}`;
      })
      .join('\n\n');
  }

  finalize(): void {
    const proto = this.protocol();
    if (!proto || this.finalizing() || this.savingTop()) return;
    this.finalizing.set(true);
    // Erst die TOP-Texte zum Protokoll-Markdown zusammensetzen + speichern,
    // dann finalisieren/rendern.
    this.api.updateProtocol(proto.id, this.assembleMarkdown()).subscribe({
      next: (saved) => {
        this.protocol.set(saved);
        this.doFinalize(saved.id);
      },
      error: () => {
        this.finalizing.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.saveFailed'));
      },
    });
  }

  private doFinalize(protocolId: Uuid): void {
    this.api.finalizeProtocol(protocolId).subscribe({
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

  // --- Tagesordnung (#10/#58) ----------------------------------------------
  private loadAgenda(meetingId: Uuid): void {
    this.api.listAgenda(meetingId).subscribe({
      next: (rows) => {
        this.agenda.set(rows);
        // Bleibt der gewählte TOP gültig? Sonst den ersten wählen.
        const sel = this.selectedTopId();
        if (!sel || !rows.some((r) => r.id === sel)) {
          this.selectedTopId.set(rows[0]?.id ?? null);
        }
      },
      error: () => this.agenda.set([]),
    });
    if (this.canManage()) this.refreshAssignable(meetingId);
  }

  private refreshAssignable(meetingId: Uuid): void {
    this.api.listAssignableApplications(meetingId).subscribe({
      next: (rows) => this.assignable.set(rows),
      error: () => this.assignable.set([]),
    });
  }

  addToAgenda(): void {
    const m = this.meeting();
    const appId = this.agendaPick();
    if (!m || !appId || this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.addAgendaItem(m.id, appId).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.agendaPick.set('');
        this.refreshAssignable(m.id);
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  addFreetext(): void {
    const m = this.meeting();
    const title = this.agendaFreetext().trim();
    if (!m || !title || this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.addAgendaFreetext(m.id, title).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.agendaFreetext.set('');
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  removeFromAgenda(itemId: Uuid): void {
    const m = this.meeting();
    if (!m || this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.removeAgendaItem(m.id, itemId).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.refreshAssignable(m.id);
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }


  // --- Live-Abstimmung öffnen (#Meetings) ----------------------------------
  openVoteDialog(item: AgendaItem): void {
    if (!item.applicationId) return;
    this.voteItem.set(item);
    this.voteQuestion.set(item.title ?? '');
    this.voteOptions.set('Ja\nNein\nEnthaltung');
    this.voteSecret.set(false);
    this.voteDialogOpen.set(true);
  }

  closeVoteDialog(): void {
    this.voteDialogOpen.set(false);
  }

  submitVote(): void {
    const m = this.meeting();
    const item = this.voteItem();
    const options = this.voteOptionList();
    if (!m || !item?.applicationId || options.length < 2 || this.openingVote()) return;
    this.openingVote.set(true);
    this.api
      .openMeetingVote(m.id, {
        applicationId: item.applicationId,
        question: this.voteQuestion().trim() || null,
        options,
        secret: this.voteSecret(),
      })
      .subscribe({
        next: (updated) => {
          this.openingVote.set(false);
          this.voteDialogOpen.set(false);
          this.meeting.set(updated);
          this.toast.success(this.i18n.translate('meetings.toast.voteOpened'));
        },
        error: () => {
          this.openingVote.set(false);
          this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
        },
      });
  }

  /** i18n-Map (z. B. State-Label) für die aktuelle Sprache auflösen. */
  resolveLabel(map: I18nMap): string {
    return map[this.i18n.locale()] ?? map['de'] ?? Object.values(map)[0] ?? '';
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
