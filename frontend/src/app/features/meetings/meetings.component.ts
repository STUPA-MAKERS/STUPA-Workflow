import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  type ElementRef,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
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
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  type IconName,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { MarkdownEditorComponent } from '@shared/ui/markdown-editor/markdown-editor.component';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminOptionsService } from '../../pages/admin/admin-options.service';
import { renderMarkdown } from './meetings.util';

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
    DialogComponent,
    IconComponent,
    MarkdownEditorComponent,
    LocalizedDatePipe,
    NgTemplateOutlet,
  ],
  template: `
    <header class="mtg__head">
      <div class="mtg__headRow">
        <h1 class="mtg__title">{{ 'meetings.title' | t }}</h1>
        @if (!meeting() && canManage()) {
          <app-button size="sm" (click)="openCreate()">{{ 'meetings.list.new' | t }}</app-button>
        }
      </div>
      @if (meeting(); as m) {
        <div class="mtg__meta">
          <span class="mtg__name">{{ m.title }}</span>
          @if (m.date) {
            <span class="mtg__muted">{{ m.date | ldate: 'mediumDate' }}{{ m.startTime ? ', ' + m.startTime : '' }}</span>
          }
          <app-badge [variant]="statusVariant(m.status)">
            {{ statusKey(m.status) | t }}
          </app-badge>
          @if (m.protokollantName) {
            <span class="mtg__muted">{{ 'meetings.protokollant.label' | t }}: {{ m.protokollantName }}</span>
          }
          <app-button
            variant="ghost"
            size="sm"
            class="mtg__beamerToggle"
            (click)="beamerMode.set(!beamerMode())"
          >
            {{ (beamerMode() ? 'meetings.beamer.exit' : 'meetings.beamer.enter') | t }}
          </app-button>
        </div>
      }
    </header>

    @if (showForbidden()) {
      <p class="mtg__status" role="alert">{{ 'rbac.forbidden' | t }}</p>
    } @else if (loading()) {
      <p class="mtg__status" aria-live="polite">{{ 'meetings.loading' | t }}</p>
    } @else if (error()) {
      <p class="mtg__status mtg__status--error" role="alert">{{ 'meetings.error' | t }}</p>
    } @else if (meeting(); as m) {
      <!-- Beamer-Ansicht: nur aktuelle Frage + Live-Ergebnis, keine Dialoge (#Sessions). -->
      @if (beamerMode()) {
        <section class="mtg__beamer" [attr.aria-label]="'meetings.beamer.heading' | t">
          @if (beamerVote(); as bv) {
            <app-badge [variant]="voteVariant(bv.status)">{{ voteStatusKey(bv.status) | t }}</app-badge>
            <h2 class="mtg__beamerQ">{{ bv.question || bv.title || ('meetings.vote.untitled' | t) }}</h2>
            <dl class="mtg__beamerTally">
              @for (entry of countEntries(bv); track entry.key) {
                <div class="mtg__beamerOpt" [class.mtg__beamerOpt--lead]="entry.key === bv.leading">
                  <dd>{{ entry.value }}</dd>
                  <dt>{{ voteOptionLabel(entry.key) }}</dt>
                </div>
              }
            </dl>
            @if (bv.result) {
              <span class="mtg__beamerResult">
                <app-badge [variant]="voteResultVariant(bv.result)">{{ voteResultKey(bv.result) | t }}</app-badge>
              </span>
            }
          } @else {
            <p class="mtg__beamerIdle">{{ 'meetings.beamer.idle' | t }}</p>
          }
        </section>
      }

      <!-- Mitglied: Live-Verfolgung (Protokoll lesen, offene Abstimmungen mitstimmen). -->
      @if (isFollower() && !beamerMode()) {
        <app-card [heading]="'meetings.follow.title' | t">
          <p class="mtg__lead">{{ 'meetings.follow.lead' | t }}</p>
          @for (item of agenda(); track item.id; let i = $index) {
            <article class="mtg__followTop">
              <h3 class="mtg__topTitle">{{ 'meetings.agenda.top' | t: { n: i + 1 } }}: {{ item.title || ('meetings.agenda.untitled' | t) }}</h3>
              @if (item.body) { <div class="mtg__preview" [innerHTML]="renderBody(item.body)"></div> }
              @for (vote of votesForTop(item.id); track vote.id) {
                <div class="mtg__vote">
                  <div class="mtg__voteHead">
                    <span class="mtg__voteTitle">{{ vote.question || ('meetings.vote.untitled' | t) }}</span>
                    <app-badge [variant]="voteVariant(vote.status)">{{ voteStatusKey(vote.status) | t }}</app-badge>
                    @if (vote.result) { <app-badge [variant]="voteResultVariant(vote.result)">{{ voteResultKey(vote.result) | t }}</app-badge> }
                    @if (vote.result === 'rejected' && vote.failedReason === 'quorum') {
                      <span class="mtg__quorumNote">{{ 'vote.failedQuorum' | t }}</span>
                    }
                  </div>
                  @if (vote.status === 'open' && canVote()) {
                    <div class="mtg__voteActions">
                      @for (opt of voteOptionsFor(vote); track opt) {
                        <app-button size="sm" [variant]="myChoice(vote.id) === opt ? 'primary' : 'secondary'" [loading]="casting() === vote.id" (click)="cast(vote.id, opt)">{{ voteOptionLabel(opt) }}@if (myChoice(vote.id) === opt) { <app-icon name="check" [size]="13" /> }</app-button>
                      }
                    </div>
                  }
                  @if (vote.counts && vote.status === 'closed') {
                    <dl class="mtg__tally">
                      @for (entry of countEntries(vote); track entry.key) {
                        <div [class.mtg__tally--leading]="entry.key === vote.leading"><dt>{{ voteOptionLabel(entry.key) }}</dt><dd>{{ entry.value }}</dd></div>
                      }
                    </dl>
                  }
                </div>
              }
            </article>
          } @empty {
            <p class="mtg__muted">{{ 'meetings.follow.noTops' | t }}</p>
          }
        </app-card>
      }

      @if (!beamerMode() && !isFollower()) {
      <!-- Toolbar oberhalb des Bodies: Steuerung + Einstellungen + Löschen (Icon-Buttons). -->
      <div class="mtg__toolbar" role="toolbar" [attr.aria-label]="'meetings.control.title' | t">
        @if (m.canControl) {
          <app-button variant="ghost" size="sm" [iconOnly]="true" [disabled]="m.status === 'live'" [ariaLabel]="'meetings.control.open' | t" [title]="'meetings.control.open' | t" (click)="setStatus('live')"><app-icon name="play" /></app-button>
          @if (m.status !== 'closed') {
            <app-button variant="danger" size="sm" [loading]="finalizing()" [title]="'meetings.control.closeSession' | t" (click)="closeConfirmOpen.set(true)">
              <span class="mtg__btnIcon"><app-icon name="stop" [size]="14" /> {{ 'meetings.control.closeShort' | t }}</span>
            </app-button>
          }
        }
        <span class="mtg__toolbarSpacer"></span>
        @if (m.canManage) {
          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'meetings.settings.title' | t" [title]="'meetings.settings.title' | t" (click)="openSettings(m)"><app-icon name="edit" /></app-button>
          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'meetings.delete.title' | t" [title]="'meetings.delete.title' | t" (click)="askDeleteMeeting(m)"><app-icon name="delete" /></app-button>
        }
      </div>

      <!-- 3-Spalten-Shell: TOPs links, Protokoll-Body Mitte, Anwesenheit rechts. -->
      <div class="mtg__shell">
        <!-- LINKS: Tagesordnung -->
        <aside class="mtg__side mtg__side--left" [attr.aria-label]="'meetings.agenda.title' | t">
          <h2 class="mtg__sideH">{{ 'meetings.agenda.title' | t }}</h2>
          <ol class="mtg__tocList">
            @for (item of agenda(); track item.id; let i = $index) {
              <li
                class="mtg__tocItem"
                [class.mtg__tocItem--sel]="selectedTopId() === item.id"
                [attr.draggable]="m.canWrite && !protocol()?.isFinal"
                (dragstart)="onTopDragStart(i)"
                (dragover)="onTopDragOver($event)"
                (drop)="onTopDrop(i)"
                (click)="selectTop(item.id)"
              >
                @if (m.canWrite && !protocol()?.isFinal) {
                  <span class="mtg__tocGrip" aria-hidden="true">⠿</span>
                }
                <span class="mtg__tocNum">{{ i + 1 }}</span>
                @if (renamingTopId() === item.id) {
                  <input
                    class="mtg__input mtg__tocRename"
                    [ngModel]="renameDraft()"
                    (ngModelChange)="renameDraft.set($event)"
                    (click)="$event.stopPropagation()"
                    (keyup.enter)="renameTop(item)"
                    (keyup.escape)="cancelRename()"
                    (blur)="renameTop(item)"
                    [placeholder]="'meetings.agenda.renamePlaceholder' | t"
                    [attr.aria-label]="'meetings.agenda.rename' | t"
                    name="renameTop"
                    autofocus
                  />
                } @else {
                  <span class="mtg__tocTitle">{{ item.title || ('meetings.agenda.untitled' | t) }}</span>
                }
                @if (votesForTop(item.id).length) {
                  <span class="mtg__tocNum" [attr.aria-label]="'meetings.vote.count' | t">⚖ {{ votesForTop(item.id).length }}</span>
                }
                @if (m.canWrite && !protocol()?.isFinal && !item.applicationId && renamingTopId() !== item.id) {
                  <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'meetings.agenda.rename' | t" [title]="'meetings.agenda.rename' | t" [disabled]="savingAgenda()" (click)="$event.stopPropagation(); startRename(item)"><app-icon name="edit" /></app-button>
                }
                @if (m.canWrite && !protocol()?.isFinal) {
                  <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.remove' | t" [disabled]="savingAgenda()" (click)="$event.stopPropagation(); removeFromAgenda(item.id)"><app-icon name="delete" /></app-button>
                }
              </li>
            } @empty {
              <li class="mtg__muted mtg__tocEmpty">{{ 'meetings.agenda.empty' | t }}</li>
            }
          </ol>
          @if (m.canWrite && !protocol()?.isFinal) {
            <div class="mtg__tocAddBlock">
              <p class="mtg__tocAddH">{{ 'meetings.agenda.assignHeading' | t }}</p>
              <div class="mtg__tocAdd">
                <app-select [placeholder]="'meetings.agenda.addPlaceholder' | t" [options]="assignableOptions()" [ngModel]="agendaPick()" (ngModelChange)="agendaPick.set($event)" />
                <app-button size="sm" [disabled]="!agendaPick() || savingAgenda()" (click)="addToAgenda()">{{ 'meetings.agenda.add' | t }}</app-button>
              </div>
            </div>
            <hr class="mtg__tocDiv" />
            <div class="mtg__tocAddBlock">
              <p class="mtg__tocAddH">{{ 'meetings.agenda.freetextHeading' | t }}</p>
              <div class="mtg__tocAdd">
                <input class="mtg__input" [placeholder]="'meetings.agenda.freetextPlaceholder' | t" [ngModel]="agendaFreetext()" (ngModelChange)="agendaFreetext.set($event)" (keyup.enter)="addFreetext()" name="agendaFreetext" />
                <app-button variant="secondary" size="sm" [disabled]="!agendaFreetext().trim() || savingAgenda()" (click)="addFreetext()">{{ 'meetings.agenda.addFreetext' | t }}</app-button>
              </div>
            </div>
          }
        </aside>

        <!-- MITTE: Protokoll-Body (pro-TOP-Editor + Beschlussfragen) -->
        <div class="mtg__main">
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
                  [disabled]="proto.isFinal || !m.canWrite"
                  [placeholder]="'meetings.protocol.placeholder' | t"
                  (valueChange)="onTopBodyChange(top.id, $event)"
                />

                <!-- Beschlussfragen/Abstimmungen dieses TOP (#Sessions). -->
                <div class="mtg__topVotes">
                  @for (vote of votesForTop(top.id); track vote.id) {
                    <div class="mtg__vote">
                      <div class="mtg__voteHead">
                        <span class="mtg__voteTitle">{{ vote.question || ('meetings.vote.untitled' | t) }}</span>
                        <app-badge [variant]="voteVariant(vote.status)">{{ voteStatusKey(vote.status) | t }}</app-badge>
                        @if (vote.result) { <app-badge [variant]="voteResultVariant(vote.result)">{{ voteResultKey(vote.result) | t }}</app-badge> }
                        @if (vote.result === 'rejected' && vote.failedReason === 'quorum') {
                          <span class="mtg__quorumNote">{{ 'vote.failedQuorum' | t }}</span>
                        }
                        @if (m.canManageVotes && !proto.isFinal) {
                          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'meetings.vote.delete' | t" [title]="'meetings.vote.delete' | t" [disabled]="deletingVote() === vote.id" (click)="deleteVote(vote.id)"><app-icon name="delete" /></app-button>
                        }
                      </div>
                      @if (vote.counts) {
                        <dl class="mtg__tally">
                          @for (entry of countEntries(vote); track entry.key) {
                            <div [class.mtg__tally--leading]="entry.key === vote.leading"><dt>{{ voteOptionLabel(entry.key) }}</dt><dd>{{ entry.value }}</dd></div>
                          }
                        </dl>
                      }
                      @if (vote.status === 'open' && canVote()) {
                        <div class="mtg__voteActions">
                          @for (opt of voteOptionsFor(vote); track opt) {
                            <app-button size="sm" [variant]="myChoice(vote.id) === opt ? 'primary' : 'secondary'" [loading]="casting() === vote.id" (click)="cast(vote.id, opt)">{{ voteOptionLabel(opt) }}@if (myChoice(vote.id) === opt) { <app-icon name="check" [size]="13" /> }</app-button>
                          }
                        </div>
                      }
                      @if (m.canManageVotes && vote.status === 'open') {
                        <app-button variant="danger" size="sm" (click)="closeVote(vote.id)">{{ 'meetings.vote.close' | t }}</app-button>
                      }
                    </div>
                  }
                  @if (m.canManageVotes && !proto.isFinal && canAddVote(top)) {
                    <app-button size="sm" variant="secondary" (click)="openVoteDialog(top)">
                      {{ (top.applicationId ? 'meetings.vote.openFor' : 'meetings.vote.addQuestion') | t }}
                    </app-button>
                  }
                </div>
              } @else {
                <p class="mtg__muted mtg__topEmpty">{{ 'meetings.protocol.selectTop' | t }}</p>
              }
            </div>

            <!-- Finalisieren passiert implizit beim Schließen der Sitzung (#Meetings). -->
            <div class="mtg__protoActions">
              @if (proto.isFinal) {
                <p class="mtg__muted">{{ 'meetings.protocol.finalizedHint' | t }}</p>
              } @else if (canWrite()) {
                <p class="mtg__muted">{{ 'meetings.protocol.finalizeOnClose' | t }}</p>
              }
            </div>
          }
        </div>

        <!-- RECHTS: Anwesenheit -->
        <aside class="mtg__side mtg__side--right" [attr.aria-label]="'meetings.attendance.title' | t">
          <h2 class="mtg__sideH">{{ 'meetings.attendance.title' | t }}</h2>
          <table class="mtg__attTable">
            <tbody>
              @for (a of attendance(); track a.principalId) {
                <tr class="mtg__attRow">
                  <td class="mtg__attName">
                    {{ a.displayName || a.email || a.principalId }}
                    @if (a.isSelf) { <span class="mtg__attYou">{{ 'meetings.attendance.you' | t }}</span> }
                  </td>
                  <td class="mtg__attStatus">
                    @if (m.canControl || a.isSelf) {
                      <span class="mtg__attBtns" role="group" [attr.aria-label]="'meetings.attendance.title' | t">
                        @for (s of attendanceStatuses; track s) {
                          <button
                            type="button"
                            [class]="'mtg__attBtn mtg__attBtn--' + s"
                            [class.mtg__attBtn--on]="a.status === s"
                            [attr.aria-pressed]="a.status === s"
                            [attr.aria-label]="attendanceKey(s) | t"
                            [title]="attendanceKey(s) | t"
                            [disabled]="savingAttendance()"
                            (click)="setAttendance(a, s)"
                          >
                            <app-icon [name]="attendanceIcon(s)" [size]="13" />
                          </button>
                        }
                      </span>
                    } @else {
                      <app-badge [variant]="a.status ? attBadgeVariant(a.status) : 'neutral'">
                        {{ (a.status ? attendanceKey(a.status) : 'meetings.attendance.unknown') | t }}
                      </app-badge>
                    }
                  </td>
                </tr>
              } @empty {
                <tr><td colspan="2" class="mtg__muted mtg__tocEmpty">{{ 'meetings.attendance.empty' | t }}</td></tr>
              }
            </tbody>
          </table>
        </aside>
      </div>

      <!-- Session-Abstimmungen ohne TOP-Bindung (Bestand/aktiv) — Steuerung. -->
      @if (looseVotes().length) {
        <app-card [heading]="'meetings.control.title' | t">
          <ul class="mtg__votes">
            @for (vote of looseVotes(); track vote.id) {
              <li class="mtg__vote" [class.mtg__vote--active]="vote.applicationId && vote.applicationId === m.activeApplicationId">
                <div class="mtg__voteHead">
                  <span class="mtg__voteTitle">{{ vote.question || vote.title || ('meetings.vote.untitled' | t) }}</span>
                  <app-badge [variant]="voteVariant(vote.status)">{{ voteStatusKey(vote.status) | t }}</app-badge>
                  @if (vote.applicationId && vote.applicationId === m.activeApplicationId) {
                    <app-badge variant="primary">{{ 'meetings.vote.active' | t }}</app-badge>
                  }
                  @if (vote.result) { <app-badge [variant]="voteResultVariant(vote.result)">{{ voteResultKey(vote.result) | t }}</app-badge> }
                  @if (vote.result === 'rejected' && vote.failedReason === 'quorum') {
                    <span class="mtg__quorumNote">{{ 'vote.failedQuorum' | t }}</span>
                  }
                </div>
                @if (vote.counts) {
                  <dl class="mtg__tally" [attr.aria-label]="'meetings.vote.tally' | t">
                    @for (entry of countEntries(vote); track entry.key) {
                      <div [class.mtg__tally--leading]="entry.key === vote.leading"><dt>{{ voteOptionLabel(entry.key) }}</dt><dd>{{ entry.value }}</dd></div>
                    }
                  </dl>
                }
                @if (vote.status === 'open' && canVote()) {
                  <div class="mtg__voteActions">
                    @for (opt of voteOptionsFor(vote); track opt) {
                      <app-button size="sm" [variant]="myChoice(vote.id) === opt ? 'primary' : 'secondary'" [loading]="casting() === vote.id" (click)="cast(vote.id, opt)">{{ voteOptionLabel(opt) }}@if (myChoice(vote.id) === opt) { <app-icon name="check" [size]="13" /> }</app-button>
                    }
                  </div>
                }
                @if (m.canManageVotes) {
                  <div class="mtg__voteActions">
                    @if (vote.applicationId) {
                      <app-button variant="ghost" size="sm" [disabled]="vote.applicationId === m.activeApplicationId" (click)="setActive(vote.applicationId)">{{ 'meetings.vote.setActive' | t }}</app-button>
                    }
                    @if (vote.status !== 'open') {
                      <app-button variant="primary" size="sm" [disabled]="vote.status === 'closed'" (click)="openVote(vote.id)">{{ 'meetings.vote.open' | t }}</app-button>
                    } @else {
                      <app-button variant="danger" size="sm" (click)="closeVote(vote.id)">{{ 'meetings.vote.close' | t }}</app-button>
                    }
                  </div>
                }
              </li>
            }
          </ul>
        </app-card>
      }

      <!-- Abstimmung/Beschlussfrage öffnen (Dialog) -->
      <app-dialog
        [open]="voteDialogOpen()"
        [title]="'meetings.vote.dialogTitle' | t"
        [closeLabel]="'action.cancel' | t"
        (closed)="closeVoteDialog()"
      >
        <form class="mtg__voteForm" (submit)="$event.preventDefault(); submitVote()">
          <label class="mtg__paneLabel" for="mtg-vq">{{ 'meetings.vote.question' | t }}</label>
          <input id="mtg-vq" class="mtg__input" [ngModel]="voteQuestion()" (ngModelChange)="voteQuestion.set($event)" name="vq" [placeholder]="'meetings.vote.questionPlaceholder' | t" />
          <span class="mtg__paneLabel">{{ 'meetings.vote.options' | t }}</span>
          <div class="mtg__voteFixed">
            @for (opt of FIXED_VOTE_OPTIONS; track opt) {
              <app-badge variant="neutral">{{ voteOptionLabel(opt) }}</app-badge>
            }
          </div>
          <p class="mtg__muted mtg__hint">{{ 'meetings.vote.optionsFixedHint' | t }}</p>
          <label class="mtg__voteSecret">
            <input type="checkbox" [checked]="voteSecret()" (change)="voteSecret.set($any($event.target).checked)" />
            {{ 'meetings.vote.secret' | t }}
          </label>
        </form>
        <div dialog-footer class="mtg__dialogFoot">
          <app-button variant="ghost" (click)="closeVoteDialog()">{{ 'action.cancel' | t }}</app-button>
          <app-button [disabled]="openingVote()" [loading]="openingVote()" (click)="submitVote()">
            {{ 'meetings.vote.openSubmit' | t }}
          </app-button>
        </div>
      </app-dialog>

      <!-- Sitzung schließen (unwiderruflich, finalisiert das Protokoll). -->
      <app-dialog
        [open]="closeConfirmOpen()"
        [title]="'meetings.closeConfirm.title' | t"
        [closeLabel]="'action.cancel' | t"
        (closed)="closeConfirmOpen.set(false)"
      >
        <p>{{ 'meetings.closeConfirm.body' | t }}</p>
        <div dialog-footer class="mtg__dialogFoot">
          <app-button variant="ghost" (click)="closeConfirmOpen.set(false)">{{ 'action.cancel' | t }}</app-button>
          <app-button variant="danger" [loading]="finalizing()" (click)="closeConfirmOpen.set(false); closeMeeting()">
            {{ 'meetings.closeConfirm.confirm' | t }}
          </app-button>
        </div>
      </app-dialog>
      } <!-- /@if (!beamerMode() && !isFollower()) -->
    } @else {
      <!-- Übersicht: vorhandene Sitzungen (#104) als geteilte Tabelle (#27) -->
      @if (canManage() || canWrite()) {
        <section class="mtg__listSection">
          @if (loadingList()) {
            <p class="mtg__muted" aria-live="polite">{{ 'meetings.list.loading' | t }}</p>
          } @else if (timelineEmpty()) {
            <p class="mtg__muted">{{ 'meetings.list.empty' | t }}</p>
          } @else {
            <!-- Timeline (#104): Vergangenes oben (serverseitig lazy beim Hochscrollen),
                 Anstehendes unten (lazy beim Runterscrollen). -->
            <div class="mtg__timeline" #tlScroll (scroll)="onTimelineScroll(tlScroll)">
              @if (hasMorePast()) {
                <button type="button" class="mtg__tlMore" [disabled]="loadingPast()" (click)="loadMorePast(tlScroll)">
                  <app-icon name="chevron-up" />
                  {{ (loadingPast() ? 'meetings.list.loading' : 'meetings.list.loadPast') | t }}
                </button>
              }
              @for (m of pastItems(); track m.id) {
                <ng-container *ngTemplateOutlet="tlRow; context: { $implicit: m, past: true }" />
              }
              <div class="mtg__tlNow" #nowMarker>
                <span class="mtg__tlNowLabel">{{ 'meetings.list.now' | t }}</span>
              </div>
              @for (m of upcomingItems(); track m.id) {
                <ng-container *ngTemplateOutlet="tlRow; context: { $implicit: m, past: false }" />
              } @empty {
                <p class="mtg__muted mtg__tlNoUp">{{ 'meetings.list.noUpcoming' | t }}</p>
              }
              @if (loadingUpcoming()) {
                <p class="mtg__muted mtg__tlNoUp" aria-live="polite">{{ 'meetings.list.loading' | t }}</p>
              }
            </div>

            <ng-template #tlRow let-m let-past="past">
              <article
                class="mtg__tlItem"
                [class.mtg__tlItem--past]="past"
                [class.mtg__tlItem--live]="m.status === 'live'"
                tabindex="0"
                role="button"
                [attr.aria-label]="('meetings.list.open' | t) + ': ' + m.title"
                (click)="openMeeting(m.id)"
                (keydown.enter)="openMeeting(m.id)"
              >
                <span class="mtg__tlDot" [class.mtg__tlDot--live]="m.status === 'live'"></span>
                <div class="mtg__tlBody">
                  <div class="mtg__tlMeta">
                    <span class="mtg__muted mtg__tlDate">
                      @if (m.date) {
                        {{ m.date | ldate: 'mediumDate' }}{{ m.startTime ? ', ' + m.startTime : '' }}
                      } @else {
                        {{ 'meetings.list.noDate' | t }}
                      }
                    </span>
                    <app-badge [variant]="statusVariant(m.status)">{{ statusKey(m.status) | t }}</app-badge>
                    @if (m.gremiumName) {
                      <span class="mtg__tlGremium"><app-icon name="parliament" [size]="12" /> {{ m.gremiumName }}</span>
                    }
                  </div>
                  <h3 class="mtg__tlTitle">{{ m.title }}</h3>
                  @if (m.protokollantName) {
                    <span class="mtg__muted mtg__tlProto">{{ 'meetings.protokollant.label' | t }}: {{ m.protokollantName }}</span>
                  }
                </div>
                <span class="mtg__rowActions" (click)="$event.stopPropagation()">
                  @if (canManageAny()) {
                    <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'meetings.settings.title' | t" [title]="'meetings.settings.title' | t" (click)="openSettings(m)">
                      <app-icon name="edit" />
                    </app-button>
                    <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'meetings.delete.title' | t" [title]="'meetings.delete.title' | t" (click)="askDeleteMeeting(m)">
                      <app-icon name="delete" />
                    </app-button>
                  }
                  <app-icon name="chevron-down" class="mtg__openIcon" />
                </span>
              </article>
            </ng-template>
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

    <!-- Einstellungen: Protokollant + Datum/Zeit (Toolbar ODER Listen-Edit), top-level. -->
    <app-dialog
      [open]="settingsMeeting() !== null"
      [title]="'meetings.settings.title' | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="closeSettings()"
    >
      <form class="mtg__createForm" (submit)="$event.preventDefault(); saveSettings()">
        <app-select
          name="setProt"
          [label]="'meetings.protokollant.label' | t"
          [options]="protokollantOptions()"
          [ngModel]="settingsProtokollant()"
          (ngModelChange)="settingsProtokollant.set($event)"
        />
        <app-datepicker
          [label]="'meetings.create.date' | t"
          [ngModel]="settingsDate()"
          (ngModelChange)="settingsDate.set($event)"
          name="setDate"
        />
        <label class="mtg__paneLabel" for="mtg-set-time">{{ 'meetings.create.time' | t }}</label>
        <input id="mtg-set-time" class="mtg__input" type="time" [ngModel]="settingsTime()" (ngModelChange)="settingsTime.set($event)" name="setTime" />
      </form>
      <div dialog-footer class="mtg__dialogFoot">
        <app-button variant="ghost" (click)="closeSettings()">{{ 'action.cancel' | t }}</app-button>
        <app-button [loading]="savingSettings()" (click)="saveSettings()">{{ 'action.save' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Sitzung löschen (Bestätigung), top-level. -->
    <app-dialog
      [open]="confirmDeleteMeeting() !== null"
      [title]="'meetings.delete.title' | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="confirmDeleteMeeting.set(null)"
    >
      <p>{{ 'meetings.delete.body' | t: { name: confirmDeleteMeeting()?.title ?? '' } }}</p>
      <div dialog-footer class="mtg__dialogFoot">
        <app-button variant="ghost" (click)="confirmDeleteMeeting.set(null)">{{ 'action.cancel' | t }}</app-button>
        <app-button variant="danger" [loading]="deletingMeeting()" (click)="doDeleteMeeting()">{{ 'meetings.delete.confirm' | t }}</app-button>
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
      .mtg__head {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        width: 100%;
      }
      .mtg__headRow {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
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
      .mtg__quorumNote {
        font-size: var(--fs-xs);
        color: var(--color-danger);
        font-weight: var(--fw-medium);
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
        /* Stimm-Buttons bleiben beim Scrollen erreichbar (#Meetings). */
        position: sticky;
        bottom: 0;
        z-index: 1;
        margin-top: var(--space-2);
        padding: var(--space-2);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
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
        gap: var(--space-2);
      }
      .mtg__tocItem {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        padding: var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        cursor: pointer;
        min-width: 0;
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
      .mtg__tocRename {
        flex: 1;
        min-width: 0;
        padding: var(--space-1) var(--space-2);
        font-size: var(--fs-sm);
      }
      .mtg__tocEmpty {
        padding: var(--space-4) var(--space-2);
        text-align: center;
        border: var(--border-width) dashed var(--color-border);
        border-radius: var(--radius-md);
        font-size: var(--fs-sm);
      }
      .mtg__tocAddBlock {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .mtg__tocAddH {
        margin: 0;
        font-size: var(--fs-sm);
        font-weight: var(--fw-semibold);
        color: var(--color-text-muted);
      }
      .mtg__tocDiv {
        border: 0;
        border-top: var(--border-width) solid var(--color-border);
        margin: var(--space-2) 0;
        width: 100%;
      }
      .mtg__tocAdd {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        align-items: stretch;
      }
      .mtg__tocAdd > app-select,
      .mtg__tocAdd > .mtg__input {
        width: 100%;
        min-width: 0;
      }
      .mtg__tocAdd > app-button {
        align-self: stretch;
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
        display: grid;
        place-items: center;
        min-height: 12rem;
        margin: 0;
        padding: var(--space-5);
        text-align: center;
        border: var(--border-width) dashed var(--color-border);
        border-radius: var(--radius-md);
      }
      .mtg__attTable {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
      }
      .mtg__attRow td {
        padding: var(--space-1) var(--space-1);
        border-bottom: var(--border-width) solid var(--color-border);
        vertical-align: middle;
      }
      .mtg__attRow:last-child td {
        border-bottom: none;
      }
      .mtg__attName {
        font-weight: var(--fw-medium);
        width: 100%;
      }
      .mtg__attYou {
        font-size: var(--fs-xs);
        font-weight: var(--fw-normal);
        color: var(--color-text-muted);
        margin-left: var(--space-1);
      }
      .mtg__attStatus {
        text-align: end;
        white-space: nowrap;
      }
      .mtg__attBtns {
        display: inline-flex;
        gap: 3px;
      }
      .mtg__attBtn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.5rem;
        height: 1.5rem;
        padding: 0;
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-sm);
        background: transparent;
        color: var(--color-text-muted);
        cursor: pointer;
      }
      .mtg__attBtn:hover:not(:disabled) {
        background: var(--color-surface-sunken);
      }
      .mtg__attBtn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .mtg__attBtn--on.mtg__attBtn--present {
        background: var(--color-success);
        border-color: var(--color-success);
        color: #fff;
      }
      .mtg__attBtn--on.mtg__attBtn--excused {
        background: var(--color-warning);
        border-color: var(--color-warning);
        color: #1a1a1a;
      }
      .mtg__attBtn--on.mtg__attBtn--absent {
        background: var(--color-danger);
        border-color: var(--color-danger);
        color: #fff;
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
      .mtg__voteFixed {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-2);
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
      .mtg__beamerToggle {
        margin-left: auto;
      }
      .mtg__topVotes {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        margin-top: var(--space-3);
      }
      .mtg__followTop {
        padding: var(--space-3) 0;
        border-bottom: var(--border-width) solid var(--color-border);
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .mtg__danger {
        border-top: var(--border-width) solid var(--color-danger);
        padding-top: var(--space-3);
        margin-top: var(--space-4);
      }
      .mtg__beamer {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--space-6);
        padding: clamp(var(--space-6), 6vw, var(--space-8)) var(--space-4);
        text-align: center;
      }
      .mtg__beamerQ {
        font-size: clamp(1.75rem, 4vw, 3rem);
        font-weight: var(--fw-bold, 700);
        margin: 0;
        max-width: 24ch;
      }
      .mtg__beamerTally {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: var(--space-4);
        margin: 0;
      }
      .mtg__beamerOpt {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        min-width: 7rem;
        padding: var(--space-4) var(--space-5);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
      }
      .mtg__beamerOpt dd {
        margin: 0;
        font-size: clamp(2rem, 5vw, 3.5rem);
        font-weight: var(--fw-bold, 700);
        font-variant-numeric: tabular-nums;
        line-height: 1;
      }
      .mtg__beamerOpt dt {
        color: var(--color-text-muted);
        font-size: var(--fs-md);
      }
      .mtg__beamerOpt--lead {
        border-color: var(--color-success);
        background: color-mix(in srgb, var(--color-success) 14%, var(--color-surface));
      }
      .mtg__beamerOpt--lead dt {
        color: var(--color-success);
      }
      .mtg__beamerResult {
        font-size: var(--fs-lg);
      }
      .mtg__beamerIdle {
        color: var(--color-text-muted);
        font-size: var(--fs-lg);
        padding: var(--space-8) 0;
      }
      .mtg__toolbar {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
        flex-wrap: wrap;
        width: 100%;
        max-width: var(--layout-max-width);
        margin-inline: auto;
      }
      .mtg__toolbarSpacer {
        margin-left: auto;
      }
      .mtg__btnIcon {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
      }
      /* Breakout-Grid: Tagesordnung im linken Rand, Anwesenheit im rechten Rand,
         Protokoll-Body zentriert auf Body-Breite (analog Budget-Dashboard). */
      .mtg__shell {
        display: grid;
        grid-template-columns:
          minmax(13rem, 1fr)
          minmax(0, var(--layout-max-width))
          minmax(13rem, 1fr);
        gap: var(--space-5);
        align-items: start;
      }
      .mtg__side {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        padding: var(--space-4);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        background: var(--color-surface);
        position: sticky;
        top: var(--space-4);
        max-height: calc(100vh - var(--space-6));
        overflow-y: auto;
        width: 100%;
      }
      .mtg__side--left {
        justify-self: end;
        max-width: 18rem;
      }
      .mtg__side--right {
        justify-self: start;
        max-width: 18rem;
      }
      /* Schmaler: Anwesenheit unter den Body, Tagesordnung bleibt links. */
      @media (max-width: 60rem) {
        .mtg__shell {
          grid-template-columns: minmax(10rem, 16rem) minmax(0, 1fr);
        }
        .mtg__side--left {
          justify-self: stretch;
          max-width: none;
        }
        .mtg__side--right {
          grid-column: 1 / -1;
          justify-self: stretch;
          max-width: none;
          position: static;
        }
      }
      @media (max-width: 40rem) {
        .mtg__shell {
          grid-template-columns: 1fr;
        }
        .mtg__side {
          position: static;
          max-width: none;
        }
      }
      .mtg__sideH {
        margin: 0;
        font-size: var(--fs-md);
      }
      .mtg__main {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        min-width: 0;
      }
      /* Pro-TOP-Editor: deutlich höhere Schreibfläche (#Sessions). Der Editor
         kapselt seine Styles, daher ::ng-deep auf Host + ProseMirror-Fläche. */
      .mtg__main app-markdown-editor {
        display: block;
      }
      .mtg__main app-markdown-editor ::ng-deep .mde__host {
        min-height: 24rem;
      }
      .mtg__main app-markdown-editor ::ng-deep .mde__host .ProseMirror {
        min-height: 22rem;
      }
      .mtg__rowActions {
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        justify-content: flex-end;
      }
      /* --- Timeline (#104) --- */
      .mtg__timeline {
        position: relative;
        max-height: min(70vh, 640px);
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        padding: var(--space-2) var(--space-1);
      }
      /* durchgehende Rail-Linie hinter den Punkten */
      .mtg__timeline::before {
        content: '';
        position: absolute;
        left: calc(var(--space-1) + 15px);
        top: 0;
        bottom: 0;
        width: var(--border-width);
        background: var(--color-border);
      }
      .mtg__tlMore {
        z-index: 1;
        align-self: center;
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: 999px;
        color: var(--color-text-muted);
        padding: var(--space-1) var(--space-3);
        font-size: var(--fs-sm);
        cursor: pointer;
      }
      .mtg__tlMore:hover {
        color: var(--color-text);
        border-color: var(--color-primary);
      }
      .mtg__tlItem {
        position: relative;
        display: flex;
        align-items: flex-start;
        gap: var(--space-3);
        padding: var(--space-3) var(--space-3) var(--space-3) var(--space-6);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
        cursor: pointer;
        transition: border-color 0.12s ease, background 0.12s ease;
      }
      .mtg__tlItem:hover {
        border-color: var(--color-primary);
      }
      .mtg__tlItem:focus-visible {
        outline: 2px solid var(--color-primary);
        outline-offset: 2px;
      }
      .mtg__tlItem--past {
        opacity: 0.82;
      }
      .mtg__tlItem--live {
        border-color: var(--color-primary);
        background: var(--color-primary-subtle);
        opacity: 1;
      }
      .mtg__tlDot {
        position: absolute;
        left: 10px;
        top: var(--space-4);
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--color-text-muted);
        box-shadow: 0 0 0 3px var(--color-surface);
      }
      .mtg__tlItem--live .mtg__tlDot,
      .mtg__tlDot--live {
        background: var(--color-primary);
      }
      .mtg__tlBody {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      .mtg__tlMeta {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
      }
      .mtg__tlDate {
        font-size: var(--fs-sm);
      }
      .mtg__tlGremium {
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        font-size: var(--fs-sm);
        color: var(--color-text-muted);
      }
      .mtg__tlTitle {
        margin: 0;
        font-size: var(--fs-md);
        font-weight: var(--fw-semibold);
      }
      .mtg__tlProto {
        font-size: var(--fs-sm);
      }
      .mtg__tlNow {
        position: relative;
        z-index: 1;
        display: flex;
        align-items: center;
        padding-left: var(--space-6);
        margin: var(--space-1) 0;
      }
      .mtg__tlNow::after {
        content: '';
        flex: 1;
        height: var(--border-width);
        background: var(--color-primary);
        opacity: 0.4;
        margin-left: var(--space-2);
      }
      .mtg__tlNowLabel {
        font-size: var(--fs-sm);
        font-weight: var(--fw-semibold);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--color-primary);
      }
      .mtg__tlNoUp {
        padding-left: var(--space-6);
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
  /** Detail-Route (`/meetings/:id`) vs. Übersicht (`/meetings`). */
  readonly detailMode = signal(false);

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
  /** Inline-Umbenennen eines Freitext-TOP: aktiver TOP + Eingabe-Entwurf (#Sessions). */
  readonly renamingTopId = signal<Uuid | null>(null);
  readonly renameDraft = signal<string>('');

  /** Live-Abstimmung öffnen (#Meetings): Dialog-Zustand + Beschlussfrage/Optionen. */
  readonly voteDialogOpen = signal(false);
  private readonly voteItem = signal<AgendaItem | null>(null);
  readonly voteQuestion = signal<string>('');
  /** Feste Stimm-Optionen (kanonische Keys) — Pass/Fail braucht yes/no/abstain. */
  readonly FIXED_VOTE_OPTIONS = ['yes', 'no', 'abstain'] as const;
  readonly voteSecret = signal(false);
  readonly openingVote = signal(false);
  /** Anzeige-Label einer Stimm-Option (yes→Ja …); unbekannte roh. */
  voteOptionLabel(opt: string): string {
    const key = `vote.option.${opt}` as TranslationKey;
    const label = this.i18n.translate(key);
    return label === key ? opt : label;
  }
  readonly assignableOptions = computed<SelectOption[]>(() =>
    this.assignable().map((a) => ({ value: a.applicationId, label: a.title || a.applicationId })),
  );

  /** Initiales Laden der Übersicht-Timeline (erste Seite beider Richtungen). */
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

  // --- Timeline (#104) — server-seitiges Keyset-Lazy-Loading ----------------
  /** Seitengröße je Nachlade-Schritt (beide Richtungen). */
  private readonly PAGE = 15;

  /** Anstehende Sitzungen, chronologisch vorwärts (frühestes oben). */
  readonly upcomingItems = signal<Meeting[]>([]);
  /** Vergangene Sitzungen, chronologisch (ältestes oben, jüngstes am „jetzt"). */
  readonly pastItems = signal<Meeting[]>([]);
  /** Cursor der jeweils nächsten Seite (``null`` ⇒ Richtung erschöpft). */
  private upcomingCursor: string | null = null;
  private pastCursor: string | null = null;
  readonly upcomingHasMore = signal(false);
  readonly pastHasMore = signal(false);
  readonly loadingUpcoming = signal(false);
  readonly loadingPast = signal(false);
  private didInitialScroll = false;

  readonly timelineScroll = viewChild<ElementRef<HTMLElement>>('tlScroll');
  readonly nowMarker = viewChild<ElementRef<HTMLElement>>('nowMarker');

  /** „Frühere Sitzungen laden"-Affordanz (oben). */
  readonly hasMorePast = computed(() => this.pastHasMore());
  /** Übersicht leer (nach dem Laden keine Sitzung in beiden Richtungen). */
  readonly timelineEmpty = computed(
    () => !this.upcomingItems().length && !this.pastItems().length,
  );

  /**
   * Scroll-getriebenes Nachladen: nahe dem oberen Rand ⇒ ältere Vergangenheit,
   * nahe dem unteren Rand ⇒ weitere Zukunft. Beide serverseitig per Cursor.
   */
  onTimelineScroll(el: HTMLElement): void {
    if (el.scrollTop <= 80) this.loadMorePast(el);
    if (el.scrollHeight - el.scrollTop - el.clientHeight <= 80) this.loadMoreUpcoming();
  }

  /** Nächste Vergangenheits-Seite laden + Scroll-Position über die neue Höhe halten. */
  loadMorePast(el: HTMLElement): void {
    if (this.loadingPast() || !this.pastHasMore() || this.pastCursor === null) return;
    this.loadingPast.set(true);
    const prevHeight = el.scrollHeight;
    this.api
      .listMeetingsTimeline({ direction: 'past', cursor: this.pastCursor, limit: this.PAGE })
      .subscribe({
        next: (page) => {
          this.loadingPast.set(false);
          // Seite ist neueste-zuerst ⇒ umgedreht oben anfügen (älteste bleiben oben).
          this.pastItems.update((cur) => [...[...page.items].reverse(), ...cur]);
          this.pastCursor = page.nextCursor;
          this.pastHasMore.set(page.nextCursor !== null);
          requestAnimationFrame(() => {
            el.scrollTop += el.scrollHeight - prevHeight;
          });
        },
        error: () => this.loadingPast.set(false),
      });
  }

  /** Nächste Zukunfts-Seite laden + unten anfügen. */
  loadMoreUpcoming(): void {
    if (this.loadingUpcoming() || !this.upcomingHasMore() || this.upcomingCursor === null)
      return;
    this.loadingUpcoming.set(true);
    this.api
      .listMeetingsTimeline({
        direction: 'upcoming',
        cursor: this.upcomingCursor,
        limit: this.PAGE,
      })
      .subscribe({
        next: (page) => {
          this.loadingUpcoming.set(false);
          this.upcomingItems.update((cur) => [...cur, ...page.items]);
          this.upcomingCursor = page.nextCursor;
          this.upcomingHasMore.set(page.nextCursor !== null);
        },
        error: () => this.loadingUpcoming.set(false),
      });
  }

  /** Eine geänderte Sitzung in beiden Richtungen ersetzen (Settings-Save). */
  private replaceInTimeline(updated: Meeting): void {
    const repl = (list: Meeting[]): Meeting[] =>
      list.map((x) => (x.id === updated.id ? updated : x));
    this.upcomingItems.update(repl);
    this.pastItems.update(repl);
  }

  /** Eine gelöschte Sitzung aus beiden Richtungen entfernen. */
  private removeFromTimeline(id: Uuid): void {
    const rm = (list: Meeting[]): Meeting[] => list.filter((x) => x.id !== id);
    this.upcomingItems.update(rm);
    this.pastItems.update(rm);
  }

  openCreate(): void {
    this.createOpen.set(true);
  }

  /** Globale Verwalter-Rechte — Gating der Übersicht/Anlegen (ohne geladene Sitzung). */
  readonly canManageAny = computed(() => this.auth.can('meeting.manage'));
  /** Per-Sitzung-Flags aus der geladenen Sitzung (Backend, gremium-genau). */
  readonly canManage = computed(() => this.meeting()?.canManage ?? this.canManageAny());
  readonly canWrite = computed(() => this.meeting()?.canWrite ?? false);
  readonly canManageVotes = computed(() => this.meeting()?.canManageVotes ?? false);
  readonly canVote = computed(() => this.meeting()?.canVote ?? false);
  readonly canWriteGlobal = computed(() => this.auth.can('protocol.write'));
  /** Übersicht ohne Detail-Route + ohne Verwalter-Recht ⇒ keine Berechtigung. */
  readonly showForbidden = computed(
    () => !this.detailMode() && !this.canManageAny() && !this.canWriteGlobal(),
  );
  /** Mitglied ohne Schreib-/Verwaltungsrecht → reine Live-Verfolgung. */
  readonly isFollower = computed(() => {
    const m = this.meeting();
    return !!m && !m.canWrite && !m.canManage;
  });
  /** Beamer-Anzeige (nur aktuelle Frage + Live-Ergebnis, keine Dialoge). */
  readonly beamerMode = signal(false);

  /** Einstellungs-Dialog (Protokollant + Datum/Zeit) — aus Toolbar ODER Listen-Edit. */
  readonly settingsMeeting = signal<Meeting | null>(null);
  readonly settingsRoster = signal<Attendance[]>([]);
  readonly settingsProtokollant = signal<string>('');
  readonly settingsDate = signal<string>('');
  readonly settingsTime = signal<string>('');
  readonly savingSettings = signal(false);
  /** Protokollant-Auswahl aus dem Anwesenheits-Roster (alle Gremium-Mitglieder). */
  readonly protokollantOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('meetings.protokollant.none') },
    ...this.settingsRoster().map((a) => ({
      value: a.principalId,
      label: a.displayName || a.email || a.principalId,
    })),
  ]);
  /** Löschen-Bestätigung (Toolbar ODER Listen-Zeile). */
  readonly confirmDeleteMeeting = signal<Meeting | null>(null);
  readonly deletingMeeting = signal(false);
  /** Bestätigungs-Dialog fürs (unwiderrufliche) Schließen der Sitzung. */
  readonly closeConfirmOpen = signal(false);
  /** Casting-Status je Vote (für Mitglied/Protokollant-Stimmabgabe). */
  readonly casting = signal<Uuid | null>(null);
  readonly deletingVote = signal<Uuid | null>(null);
  /** Eigene Stimmwahl je Vote (lokal, fürs Hervorheben der gewählten Option). */
  private readonly myChoices = signal<Record<string, string>>({});
  myChoice(voteId: Uuid): string | null {
    return this.myChoices()[voteId] ?? null;
  }

  /** Votes eines TOP (gruppiert über agendaItemId). */
  votesForTop(topId: Uuid): MeetingVote[] {
    return (this.meeting()?.votes ?? []).filter((v) => v.agendaItemId === topId);
  }
  /** Sitzungs-Votes ohne TOP-Bindung (Bestand/aktiv) — in der Steuerung gelistet. */
  readonly looseVotes = computed<MeetingVote[]>(() =>
    (this.meeting()?.votes ?? []).filter((v) => !v.agendaItemId),
  );

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
      this.detailMode.set(!!id);
      if (id) {
        this.loadMeeting(id);
      } else {
        // Übersichts-Route `/meetings`: einzelne Sitzung lösen + Liste laden (#104).
        this.meeting.set(null);
        this.loadList();
      }
    });
    // Timeline (#104): einmalig auf den „jetzt"-Marker positionieren, sobald die
    // Liste geladen + gerendert ist — Anstehendes sichtbar, Vergangenes per Hochscrollen.
    effect(() => {
      const marker = this.nowMarker()?.nativeElement;
      const scroller = this.timelineScroll()?.nativeElement;
      // Abhängigkeiten: neu positionieren, sobald beide Richtungen eingetroffen sind.
      this.pastItems();
      this.upcomingItems();
      if (marker && scroller && !this.didInitialScroll && !this.loadingList()) {
        this.didInitialScroll = true;
        requestAnimationFrame(() => {
          scroller.scrollTop = Math.max(0, marker.offsetTop - 8);
        });
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

  /**
   * Timeline initial laden (#104): erste Zukunfts- **und** Vergangenheits-Seite
   * parallel, danach wird einmalig auf „jetzt" gescrollt (Effect oben).
   */
  private loadList(): void {
    if (!this.canManage() && !this.canWrite()) return;
    this.didInitialScroll = false;
    this.upcomingItems.set([]);
    this.pastItems.set([]);
    this.upcomingCursor = null;
    this.pastCursor = null;
    this.upcomingHasMore.set(false);
    this.pastHasMore.set(false);
    this.loadingList.set(true);
    forkJoin({
      upcoming: this.api.listMeetingsTimeline({ direction: 'upcoming', limit: this.PAGE }),
      past: this.api.listMeetingsTimeline({ direction: 'past', limit: this.PAGE }),
    }).subscribe({
      next: ({ upcoming, past }) => {
        this.loadingList.set(false);
        this.upcomingItems.set(upcoming.items);
        this.upcomingCursor = upcoming.nextCursor;
        this.upcomingHasMore.set(upcoming.nextCursor !== null);
        // „past" kommt neueste-zuerst ⇒ umdrehen: ältestes oben, jüngstes am „jetzt".
        this.pastItems.set([...past.items].reverse());
        this.pastCursor = past.nextCursor;
        this.pastHasMore.set(past.nextCursor !== null);
      },
      error: () => {
        this.loadingList.set(false);
        this.upcomingItems.set([]);
        this.pastItems.set([]);
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

  /** Sitzung unwiderruflich schließen → Status closed + Protokoll finalisieren. */
  closeMeeting(): void {
    const m = this.meeting();
    if (!m || this.finalizing()) return;
    this.api.patchMeeting(m.id, { status: 'closed' }).subscribe({
      next: (updated) => {
        this.meeting.set(updated);
        const proto = this.protocol();
        // Finalisieren passiert implizit: PDF rendern + an MAIL_LIST versenden.
        if (proto && !proto.isFinal) {
          this.finalize();
        }
      },
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

  /** Kompaktes Icon je Anwesenheits-Status: anwesend check, entschuldigt halb, abwesend remove. */
  attendanceIcon(status: AttendanceStatus): IconName {
    return status === 'present' ? 'check' : status === 'excused' ? 'half' : 'remove';
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

  /** Inline-Umbenennen eines Freitext-TOP starten (nur ohne Antrags-Bindung). */
  startRename(item: AgendaItem): void {
    if (item.applicationId) return;
    this.renamingTopId.set(item.id);
    this.renameDraft.set(item.title ?? '');
  }

  cancelRename(): void {
    this.renamingTopId.set(null);
    this.renameDraft.set('');
  }

  /** Neuen Titel eines Freitext-TOP speichern (PATCH …/agenda/{id} { title }). */
  renameTop(item: AgendaItem): void {
    // Bereits abgebrochen/umgeschaltet? Nichts tun (verhindert doppelten Blur-Save).
    if (this.renamingTopId() !== item.id) return;
    const m = this.meeting();
    const title = this.renameDraft().trim();
    // Leer oder unverändert ⇒ nur schließen, kein Request.
    if (!m || item.applicationId || !title || title === (item.title ?? '')) {
      this.cancelRename();
      return;
    }
    this.renamingTopId.set(null);
    this.savingAgenda.set(true);
    this.api.renameAgendaItem(m.id, item.id, title).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.renameDraft.set('');
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }


  // --- Live-Abstimmung/Beschlussfrage öffnen (#Sessions) -------------------
  /** App-TOP: genau eine Abstimmung; Freitext-TOP: beliebig viele Beschlussfragen. */
  canAddVote(item: AgendaItem): boolean {
    return !item.applicationId || this.votesForTop(item.id).length === 0;
  }

  openVoteDialog(item: AgendaItem): void {
    this.voteItem.set(item);
    this.voteQuestion.set(item.title ?? '');
    this.voteSecret.set(false);
    this.voteDialogOpen.set(true);
  }

  closeVoteDialog(): void {
    this.voteDialogOpen.set(false);
  }

  submitVote(): void {
    const m = this.meeting();
    const item = this.voteItem();
    const options = [...this.FIXED_VOTE_OPTIONS];
    if (!m || !item || this.openingVote()) return;
    this.openingVote.set(true);
    this.api
      .openMeetingVote(m.id, {
        agendaItemId: item.id,
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

  // --- Einstellungen (Protokollant + Datum) / Löschen / Stimmabgabe / Beamer ----
  /** Einstellungs-Dialog öffnen (aus Toolbar oder Listen-Edit) + Roster laden. */
  openSettings(m: Meeting): void {
    this.settingsMeeting.set(m);
    this.settingsProtokollant.set(m.protokollantId ?? '');
    this.settingsDate.set(m.date ?? '');
    this.settingsTime.set(m.startTime ?? '');
    this.settingsRoster.set([]);
    this.api.listAttendance(m.id).subscribe({
      next: (rows) => {
        this.settingsRoster.set(rows);
        // Auswahl erst NACH dem Laden der Optionen (erneut) setzen — sonst snappt
        // das native <select> auf „niemand", weil die Option noch fehlte.
        this.settingsProtokollant.set(m.protokollantId ?? '');
      },
      error: () => this.settingsRoster.set([]),
    });
  }

  closeSettings(): void {
    this.settingsMeeting.set(null);
  }

  /** Protokollant + Datum/Zeit in einem Zug speichern (PATCH). */
  saveSettings(): void {
    const m = this.settingsMeeting();
    if (!m || this.savingSettings()) return;
    this.savingSettings.set(true);
    this.api
      .patchMeeting(m.id, {
        protokollantId: this.settingsProtokollant() || null,
        date: this.settingsDate().trim() || null,
        startTime: this.settingsTime().trim() || null,
      })
      .subscribe({
        next: (updated) => {
          this.savingSettings.set(false);
          this.settingsMeeting.set(null);
          if (this.meeting()?.id === updated.id) this.meeting.set(updated);
          this.replaceInTimeline(updated);
          this.toast.success(this.i18n.translate('meetings.toast.settingsSaved'));
        },
        error: () => {
          this.savingSettings.set(false);
          this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
        },
      });
  }

  askDeleteMeeting(m: Meeting): void {
    this.confirmDeleteMeeting.set(m);
  }

  doDeleteMeeting(): void {
    const m = this.confirmDeleteMeeting();
    if (!m || this.deletingMeeting()) return;
    this.deletingMeeting.set(true);
    this.api.deleteMeeting(m.id).subscribe({
      next: () => {
        this.deletingMeeting.set(false);
        this.confirmDeleteMeeting.set(null);
        this.removeFromTimeline(m.id);
        this.toast.success(this.i18n.translate('meetings.toast.deleted'));
        // Aus der Detailansicht zurück zur Übersicht.
        if (this.meeting()?.id === m.id) void this.router.navigate(['/meetings']);
      },
      error: () => {
        this.deletingMeeting.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  /** Stimme abgeben (Protokollant/Mitglied mit `vote.cast`). */
  cast(voteId: Uuid, choice: string): void {
    if (this.casting()) return;
    this.casting.set(voteId);
    this.api.castBallot(voteId, choice).subscribe({
      next: () => {
        this.casting.set(null);
        this.myChoices.update((m) => ({ ...m, [voteId]: choice }));
        this.toast.success(this.i18n.translate('meetings.toast.voteCast'));
      },
      error: () => {
        this.casting.set(null);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  /** Beschlussfrage (inkl. Stimmen) löschen — nur Vote-Verwalter. */
  deleteVote(voteId: Uuid): void {
    const m = this.meeting();
    if (!m || this.deletingVote()) return;
    this.deletingVote.set(voteId);
    this.api.deleteMeetingVote(m.id, voteId).subscribe({
      next: (updated) => {
        this.deletingVote.set(null);
        this.meeting.set(updated);
        this.toast.success(this.i18n.translate('meetings.toast.voteDeleted'));
      },
      error: () => {
        this.deletingVote.set(null);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  /** Auswahl-Optionen einer Abstimmung (Fallback: Zähl-Schlüssel). */
  voteOptionsFor(vote: MeetingVote): string[] {
    return vote.options.length ? vote.options : Object.keys(vote.counts ?? {});
  }

  /** TOP-Markdown für die Live-/Beamer-Ansicht rendern (sanitisiert via [innerHTML]). */
  renderBody(body: string): string {
    return renderMarkdown(body);
  }

  /** Beamer: aktuell offene Abstimmung, sonst die zuletzt geschlossene (persistiert). */
  readonly beamerVote = computed<MeetingVote | null>(() => {
    const votes = this.meeting()?.votes ?? [];
    return (
      votes.find((v) => v.status === 'open') ??
      [...votes].reverse().find((v) => v.status === 'closed') ??
      null
    );
  });

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
        if (m.votes.some((v) => v.id === msg.voteId)) {
          this.patchVote(msg.voteId, { status: 'open', closesAt: msg.closesAt });
        } else {
          // Live geöffnete Abstimmung, die beim Laden noch nicht existierte (Follower).
          this.meeting.set({
            ...m,
            votes: [
              ...m.votes,
              {
                id: msg.voteId,
                applicationId: msg.applicationId ?? null,
                agendaItemId: msg.agendaItemId ?? null,
                title: null,
                question: msg.question ?? null,
                options: msg.options ?? [],
                status: 'open',
                result: null,
                counts: null,
                leading: null,
                closesAt: msg.closesAt,
                failedReason: null,
              },
            ],
          });
        }
        break;
      case 'vote_tally':
        this.patchVote(msg.voteId, { counts: msg.counts, leading: msg.leading });
        break;
      case 'vote_closed':
        this.patchVote(msg.voteId, {
          status: 'closed',
          result: msg.result,
          counts: msg.counts,
          failedReason: msg.failedReason ?? null,
        });
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

  /** Übersetztes Label des Abstimmungs-Ergebnisses (Angenommen/Abgelehnt/…). */
  voteResultKey(result: string | null | undefined): TranslationKey {
    return `vote.result.${result ?? 'tie'}` as TranslationKey;
  }

  /** Ergebnis-Farbe: angenommen → grün, abgelehnt → rot, sonst neutral. */
  voteResultVariant(result: string | null | undefined): BadgeVariant {
    return result === 'passed' ? 'success' : result === 'rejected' ? 'danger' : 'neutral';
  }

  countEntries(vote: MeetingVote): { key: string; value: number }[] {
    return Object.entries(vote.counts ?? {}).map(([key, value]) => ({ key, value }));
  }
}
