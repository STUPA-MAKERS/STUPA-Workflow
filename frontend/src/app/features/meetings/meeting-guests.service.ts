import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { JoinLink, Meeting, MeetingGuest, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { ToastService } from '@stupa-makers/ui-kit';
import { errorDetail } from './meetings-display.util';

/** The name of a guest: the own name, or "Gast n" once the name is pseudonymized. */
export function guestName(
  g: Pick<MeetingGuest, 'displayName' | 'number'>,
  translate: (key: TranslationKey, params?: Record<string, string | number>) => string,
): string {
  return g.displayName ?? translate('guests.pseudonym', { n: g.number });
}

/** The order of the requests: the oldest first. */
function byRequested(a: MeetingGuest, b: MeetingGuest): number {
  return a.requestedAt.localeCompare(b.requestedAt);
}

/** The order of the guests: the first admission first. */
function byAdmitted(a: MeetingGuest, b: MeetingGuest): number {
  return (a.admittedAt ?? a.requestedAt).localeCompare(b.admittedAt ?? b.requestedAt);
}

/**
 * The join requests and the guests of the open meeting, for the meeting lead
 * (public meeting with QR code, #17). Provided by `MeetingsComponent`.
 *
 * The service loads only for `canManage` on a public meeting that is not closed; the
 * server refuses everybody else (403). The lead events of the live channel
 * (`guest_requested`, `guest_updated`) keep the list current, `MeetingSessionService`
 * passes them in. Every action goes to the server; the list takes the answer.
 */
@Injectable()
export class MeetingGuestsService {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** The meeting the list belongs to, or `null` while nothing loaded. */
  readonly meetingId = signal<Uuid | null>(null);
  readonly guests = signal<MeetingGuest[]>([]);
  readonly joinLink = signal<JoinLink | null>(null);
  /** The guest with an action in flight, or `'all'` for "Alle zulassen". */
  readonly busy = signal<Uuid | 'all' | null>(null);
  readonly rotating = signal(false);

  /** The open requests, oldest first. */
  readonly pending = computed(() =>
    this.guests()
      .filter((g) => g.status === 'pending')
      .sort(byRequested),
  );
  /** The admitted guests, then those who left or were removed (they stay for the record). */
  readonly listed = computed(() => {
    const rows = this.guests().filter((g) => g.status !== 'pending' && g.status !== 'rejected');
    return [
      ...rows.filter((g) => g.status === 'admitted').sort(byAdmitted),
      ...rows.filter((g) => g.status !== 'admitted').sort(byAdmitted),
    ];
  });
  readonly admittedCount = computed(
    () => this.guests().filter((g) => g.status === 'admitted').length,
  );

  /**
   * The guest counts of a meeting: the loaded list for the lead, else the counts of the
   * meeting payload (members see the admitted guests, never the requests).
   */
  countsFor(m: Meeting): { pending: number; admitted: number } {
    if (this.meetingId() === m.id) {
      return { pending: this.pending().length, admitted: this.admittedCount() };
    }
    return { pending: m.pendingGuests, admitted: m.admittedGuests };
  }

  /** The last synced state, so a repeated meeting signal does not load again. */
  private key = '';
  private code: string | null = null;

  /**
   * Follow the meeting: load the list and the join link while the lead may manage the
   * public participation, clear both otherwise. A changed join code reads the link again.
   */
  sync(m: Meeting | null): void {
    const active = !!m && m.canManage && m.publicJoin && m.status !== 'closed';
    if (!active || !m) {
      this.key = '';
      this.code = null;
      this.meetingId.set(null);
      this.guests.set([]);
      this.joinLink.set(null);
      return;
    }
    const key = m.id;
    if (key !== this.key) {
      this.key = key;
      this.code = m.joinCode;
      this.meetingId.set(m.id);
      this.guests.set([]);
      this.joinLink.set(null);
      this.reload();
      this.loadLink();
    } else if (m.joinCode && m.joinCode !== this.code) {
      this.code = m.joinCode;
      this.loadLink();
    }
  }

  /** Read the requests and the guests again (quiet). */
  reload(): void {
    const id = this.meetingId();
    if (!id) return;
    this.api.listMeetingGuests(id).subscribe({
      next: (rows) => {
        if (this.meetingId() === id) this.guests.set(rows);
      },
      error: () => {},
    });
  }

  private loadLink(): void {
    const id = this.meetingId();
    if (!id) return;
    this.api.getJoinLink(id).subscribe({
      next: (link) => {
        if (this.meetingId() === id) this.joinLink.set(link);
      },
      error: () => {},
    });
  }

  /** A lead event of the live channel: a new request, or a changed or voided one. */
  apply(guest: MeetingGuest): void {
    if (!this.meetingId()) return;
    this.guests.update((rows) => {
      const rest = rows.filter((g) => g.id !== guest.id);
      return guest.status === 'expired' ? rest : [...rest, guest];
    });
  }

  admit(guest: MeetingGuest): void {
    this.decide(guest, 'admit');
  }

  reject(guest: MeetingGuest): void {
    this.decide(guest, 'reject');
  }

  remove(guest: MeetingGuest): void {
    this.decide(guest, 'remove');
  }

  private decide(guest: MeetingGuest, action: 'admit' | 'reject' | 'remove'): void {
    const id = this.meetingId();
    if (!id || this.busy()) return;
    this.busy.set(guest.id);
    this.api.decideMeetingGuest(id, guest.id, action).subscribe({
      next: (updated) => {
        this.busy.set(null);
        this.apply(updated);
      },
      error: (err: unknown) => this.failed(err),
    });
  }

  /** The lead corrects the name of a guest (an offensive or a misspelled name). */
  rename(guest: MeetingGuest, displayName: string): void {
    const id = this.meetingId();
    const name = displayName.trim();
    if (!id || this.busy() || name.length < 2 || name === guest.displayName) return;
    this.busy.set(guest.id);
    this.api.renameMeetingGuest(id, guest.id, name).subscribe({
      next: (updated) => {
        this.busy.set(null);
        this.apply(updated);
      },
      error: (err: unknown) => this.failed(err),
    });
  }

  /** "Alle zulassen": every open request at once. */
  admitAll(): void {
    const id = this.meetingId();
    if (!id || this.busy() || !this.pending().length) return;
    this.busy.set('all');
    this.api.admitAllMeetingGuests(id).subscribe({
      next: (rows) => {
        this.busy.set(null);
        rows.forEach((g) => this.apply(g));
        this.toast.success(this.i18n.translate('guests.toast.admittedAll', { n: rows.length }));
      },
      error: (err: unknown) => this.failed(err),
    });
  }

  /** "Neuen Link erzeugen": a new code; the old link no longer works, open requests lapse. */
  rotate(): void {
    const id = this.meetingId();
    if (!id || this.rotating()) return;
    this.rotating.set(true);
    this.api.rotateJoinCode(id).subscribe({
      next: (link) => {
        this.rotating.set(false);
        this.code = link.joinCode;
        this.joinLink.set(link);
        this.guests.update((rows) => rows.filter((g) => g.status !== 'pending'));
        this.toast.success(this.i18n.translate('guests.toast.rotated'));
      },
      error: (err: unknown) => {
        this.rotating.set(false);
        this.report(err);
      },
    });
  }

  private failed(err: unknown): void {
    this.busy.set(null);
    this.report(err);
    // The request may have changed in the meantime (another lead, a withdrawal).
    this.reload();
  }

  private report(err: unknown): void {
    const detail = errorDetail(err);
    const base = this.i18n.translate('meetings.toast.actionFailed');
    this.toast.error(detail ? `${base}: ${detail}` : base);
  }
}
