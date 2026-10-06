import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { AgendaItem, Attendance, HandoverMode, Meeting, Uuid } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { MeetingSessionService } from './meeting-session.service';
import { MeetingsTimelineService } from './meetings-timeline.service';
import { errorCode, errorDetail } from './meetings-display.util';

/** The refusals of a handover that the dialog explains in its body. */
const HANDOVER_REFUSALS = new Set([
  'protokollant_needs_protocol_write',
  'no_next_item',
  'already_protokollant',
]);

/**
 * Which meeting dialog is open, and the meeting actions that come from the dock.
 *
 * The dialogs (settings, delete, close, agenda item, vote) are components of their
 * own. They call the API themselves and report the result; this service opens them
 * and puts the result into the page state: the loaded meeting and the list.
 * MeetingsComponent provides this service.
 */
@Injectable()
export class MeetingDialogsService {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly session = inject(MeetingSessionService);
  private readonly timeline = inject(MeetingsTimelineService);

  /** "Sitzung bearbeiten", from a list row or from the meeting page. */
  readonly settingsMeeting = signal<Meeting | null>(null);
  /** "Sitzung löschen", from a list row or from the meeting page. */
  readonly deleteMeeting = signal<Meeting | null>(null);
  /** "Sitzung schließen?" for the loaded meeting. */
  readonly closeOpen = signal(false);
  /** "TOP hinzufügen" for the loaded meeting. */
  readonly agendaOpen = signal(false);
  /** "Abstimmung öffnen" for this agenda item of the loaded meeting. */
  readonly voteItem = signal<AgendaItem | null>(null);
  /** "Protokollführung übergeben" to this member of the loaded live meeting (Z3). */
  readonly handoverTarget = signal<Attendance | null>(null);
  /** The handover request runs. */
  readonly handoverSaving = signal(false);
  /** The `code` of the last refusal of the handover, for the dialog body. */
  readonly handoverRefusal = signal<string | null>(null);

  openSettings(m: Meeting): void {
    this.settingsMeeting.set(m);
  }

  closeSettings(): void {
    this.settingsMeeting.set(null);
  }

  askDeleteMeeting(m: Meeting): void {
    this.deleteMeeting.set(m);
  }

  cancelDelete(): void {
    this.deleteMeeting.set(null);
  }

  /** The server changed a meeting: put it into the page and the list. */
  applyUpdated(updated: Meeting): void {
    if (this.session.meeting()?.id === updated.id) this.session.meeting.set(updated);
    this.timeline.replaceInTimeline(updated);
  }

  /** The settings dialog saved. */
  settingsSaved(updated: Meeting): void {
    this.settingsMeeting.set(null);
    this.applyUpdated(updated);
  }

  /** The delete dialog deleted the meeting. From its page, go back to the list. */
  meetingDeleted(id: Uuid): void {
    this.deleteMeeting.set(null);
    this.timeline.removeFromTimeline(id);
    if (this.session.meeting()?.id === id) void this.router.navigate(['/meetings']);
  }

  /** The close dialog closed the meeting. The protocol stays a draft (O13). */
  meetingClosed(updated: Meeting): void {
    this.closeOpen.set(false);
    this.applyUpdated(updated);
  }

  /** The vote dialog opened a vote. */
  voteOpened(updated: Meeting): void {
    this.voteItem.set(null);
    this.applyUpdated(updated);
  }

  /**
   * Name the minute-taker of a planned meeting in one PATCH, straight from the
   * meeting page. The settings dialog stays the place for the date and the time.
   */
  setProtokollant(m: Meeting, principalId: string): void {
    this.api.patchMeeting(m.id, { protokollantId: principalId }).subscribe({
      next: (updated) => {
        this.applyUpdated(updated);
        this.toast.success(this.i18n.translate('meetings.toast.protokollantSet'));
      },
      error: (err: unknown) => this.keeperChangeFailed(err),
    });
  }

  /** Open the handover dialog for a member picked in the dock. */
  askHandover(member: Attendance): void {
    this.handoverRefusal.set(null);
    this.handoverSaving.set(false);
    this.handoverTarget.set(member);
  }

  closeHandover(): void {
    this.handoverTarget.set(null);
    this.handoverRefusal.set(null);
  }

  /**
   * Hand the minutes of a live meeting over (Z3): `now` at once, `next_item` with the
   * next agenda item. A refusal the dialog can explain stays in the dialog: 422
   * `protokollant_needs_protocol_write` (O20), 409 `no_next_item` (the last TOP) and
   * 409 `already_protokollant`. Any other refusal is a toast.
   */
  handOver(m: Meeting, principalId: Uuid, mode: HandoverMode): void {
    this.handoverSaving.set(true);
    this.handoverRefusal.set(null);
    this.api.handOverProtokollant(m.id, principalId, mode).subscribe({
      next: (updated) => {
        this.handoverSaving.set(false);
        this.closeHandover();
        this.applyUpdated(updated);
        this.toast.success(
          this.i18n.translate(
            mode === 'now' ? 'meetings.toast.handedOver' : 'meetings.toast.handoverPlanned',
          ),
        );
      },
      error: (err: unknown) => {
        this.handoverSaving.set(false);
        const code = errorCode(err);
        if (HANDOVER_REFUSALS.has(code)) {
          this.handoverRefusal.set(code);
          return;
        }
        this.keeperChangeFailed(err);
      },
    });
  }

  /** Discard the planned handover of a live meeting. */
  cancelHandover(m: Meeting): void {
    this.api.cancelProtokollantHandover(m.id).subscribe({
      next: (updated) => {
        this.applyUpdated(updated);
        this.toast.success(this.i18n.translate('meetings.toast.handoverDiscarded'));
      },
      error: (err: unknown) => this.keeperChangeFailed(err),
    });
  }

  private keeperChangeFailed(err: unknown): void {
    if (errorCode(err) === 'protokollant_needs_protocol_write') {
      this.toast.error(this.i18n.translate('meetings.toast.needsProtocolWrite'));
      return;
    }
    const detail = errorDetail(err);
    const base = this.i18n.translate('meetings.toast.actionFailed');
    this.toast.error(detail ? `${base}: ${detail}` : base);
  }
}
