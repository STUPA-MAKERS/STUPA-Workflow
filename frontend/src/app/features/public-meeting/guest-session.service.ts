import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, type OnDestroy, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { USE_MOCK_API } from '@core/api/api.config';
import type { GuestMe, PublicMeetingHead } from '@core/api/models';
import { WsService, type MeetingChannel } from '@core/ws/ws.service';
import type { ServerMessage } from '@core/ws/ws-messages';
import { AltchaService } from '../apply/altcha.service';

/** What the join page shows. */
export type GuestPageState =
  | 'loading'
  /** The code is unknown: the page offers to type it again. */
  | 'unknown'
  /** The meeting is no longer public. */
  | 'notPublic'
  /** The meeting is closed. */
  | 'closed'
  /** No request of this device: the join form. */
  | 'join'
  | 'pending'
  | 'rejected'
  | 'removed'
  | 'admitted'
  /** The page could not reach the server. */
  | 'error';

/** The refetch after a live event waits this long, so a burst of events reads once (ms). */
export const GUEST_REFRESH_MS = 300;
/** The guest channel reconnects after this delay times the attempt (ms). */
const RECONNECT_MS = 2000;
const MAX_ATTEMPTS = 5;

/** The problem code of an HTTP error, or an empty string. */
function codeOf(err: unknown): string {
  if (!(err instanceof HttpErrorResponse)) return '';
  const body = err.error as { code?: unknown } | null;
  return typeof body?.code === 'string' ? body.code : '';
}

/**
 * The join page of a public meeting (`/j/:code`, #17): the head of the meeting, the own
 * request of this device and the participant view after the admission.
 *
 * The device cookie (HttpOnly) carries the participation; the page never holds a token.
 * The guest channel (`/api/public/meetings/{code}/ws`) tells about a decision of the
 * lead, the item that runs now and the votes; every event reads `GET …/me` again, so
 * the page never needs a name of another person. Provided by the page.
 */
@Injectable()
export class GuestSessionService implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly ws = inject(WsService);
  private readonly altcha = inject(AltchaService);
  private readonly useMock = inject(USE_MOCK_API);

  readonly code = signal('');
  readonly head = signal<PublicMeetingHead | null>(null);
  readonly me = signal<GuestMe | null>(null);
  /** The head or the own state loads, or the page could not load them. */
  readonly loading = signal(true);
  private readonly failure = signal<'unknown' | 'notPublic' | 'error' | null>(null);
  readonly joining = signal(false);
  readonly saving = signal(false);
  /** The code of the last refused join (`altcha_failed`, `retry_later`, …), for the page. */
  readonly joinError = signal<string | null>(null);
  /** When the last `me` arrived: the base of the countdown to a new request. */
  readonly fetchedAt = signal(0);
  /**
   * The guest was admitted while a vote was open (seen on this page): the vote page says
   * that the guest can still vote and that the count of voters is fixed at the close.
   */
  readonly admittedDuringVote = signal(false);

  readonly state = computed<GuestPageState>(() => {
    if (this.loading()) return 'loading';
    const failure = this.failure();
    if (failure) return failure;
    const me = this.me();
    const head = me?.meeting ?? this.head();
    if (head?.status === 'closed') return 'closed';
    if (!me || me.status === 'left') return 'join';
    return me.status;
  });

  private channel: MeetingChannel | null = null;
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private attempts = 0;
  private closed = false;

  /** Open the page for a code: the head, then the own request of this device. */
  load(code: string): void {
    this.code.set(code);
    this.loading.set(true);
    this.failure.set(null);
    this.api.publicMeeting(code).subscribe({
      next: (head) => {
        this.head.set(head);
        this.refresh(true);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.fail(err);
      },
    });
  }

  /** Read the own request again. A device without one gets the join form. */
  refresh(first = false): void {
    const code = this.code();
    this.api.guestMe(code).subscribe({
      next: (me) => {
        this.adopt(me);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        const status = err instanceof HttpErrorResponse ? err.status : 0;
        const c = codeOf(err);
        if (status === 401 || c === 'guest_not_found' || c === 'guest_token_missing') {
          this.me.set(null);
          this.disconnect();
          return;
        }
        if (!first || c) this.fail(err);
      },
    });
  }

  /** Ask to join with a name. ALTCHA runs in the background before the send. */
  async join(displayName: string): Promise<void> {
    const name = displayName.trim();
    if (this.joining() || name.length < 2) return;
    this.joining.set(true);
    this.joinError.set(null);
    let solution: string | null;
    try {
      solution = await this.altcha.solve();
    } catch {
      this.joining.set(false);
      this.joinError.set('altcha_failed');
      return;
    }
    this.api.joinPublicMeeting(this.code(), name, solution).subscribe({
      next: (me) => {
        this.joining.set(false);
        this.adopt(me);
      },
      error: (err: unknown) => {
        this.joining.set(false);
        const c = codeOf(err);
        if (c === 'already_admitted' || c === 'retry_later') {
          this.refresh();
          return;
        }
        if (c === 'meeting_not_public' || c === 'join_code_unknown' || c === 'meeting_closed') {
          this.load(this.code());
          return;
        }
        this.joinError.set(c || (err instanceof HttpErrorResponse && err.status === 429 ? 'rate_limited' : 'error'));
      },
    });
  }

  /** Change the name of an open request. */
  rename(displayName: string): void {
    const name = displayName.trim();
    if (this.saving() || name.length < 2) return;
    this.saving.set(true);
    this.api.renameGuestMe(this.code(), name).subscribe({
      next: (me) => {
        this.saving.set(false);
        this.adopt(me);
      },
      error: () => {
        this.saving.set(false);
        this.refresh();
      },
    });
  }

  /** Withdraw the request or leave the meeting; the own name becomes "Gast n" at once. */
  leave(): void {
    if (this.saving()) return;
    this.saving.set(true);
    this.api.leavePublicMeeting(this.code()).subscribe({
      next: () => {
        this.saving.set(false);
        this.me.set(null);
        this.disconnect();
      },
      error: () => {
        this.saving.set(false);
        this.refresh();
      },
    });
  }

  private adopt(me: GuestMe): void {
    const before = this.me();
    const openVote = !!me.view?.votes.some((v) => v.status === 'open');
    if (before?.status === 'pending' && me.status === 'admitted' && openVote) {
      this.admittedDuringVote.set(true);
    } else if (!openVote) {
      this.admittedDuringVote.set(false);
    }
    this.me.set(me);
    this.head.set(me.meeting);
    this.fetchedAt.set(Date.now());
    if (me.status === 'pending' || me.status === 'admitted') this.connect();
    else this.disconnect();
  }

  private fail(err: unknown): void {
    const c = codeOf(err);
    if (c === 'join_code_unknown' || (err instanceof HttpErrorResponse && err.status === 404 && !c)) {
      this.failure.set('unknown');
    } else if (c === 'meeting_not_public') {
      this.failure.set('notPublic');
      this.me.set(null);
      this.disconnect();
    } else {
      this.failure.set('error');
    }
  }

  /** Read `me` again shortly after a live event; a burst of events reads once. */
  private scheduleRefresh(): void {
    if (this.refreshTimer !== null) return;
    this.refreshTimer = setTimeout(() => {
      this.refreshTimer = null;
      this.refresh();
    }, GUEST_REFRESH_MS);
  }

  private connect(): void {
    // The mock API (dev, screenshots) has no socket server.
    if (this.channel || this.useMock || this.closed) return;
    const ch = this.ws.connectGuest(this.code());
    this.channel = ch;
    ch.messages$.subscribe({
      next: (msg) => this.onLive(msg),
      complete: () => this.onClosed(ch),
      error: () => this.onClosed(ch),
    });
    ch.send({ type: 'subscribe' });
  }

  private onLive(msg: ServerMessage): void {
    this.attempts = 0;
    if (msg.type === 'error') return;
    if (msg.type === 'guest_status' && msg.reason === 'public_off') {
      this.failure.set('notPublic');
    }
    this.scheduleRefresh();
  }

  /** The socket ended: reconnect while the request or the participation still runs. */
  private onClosed(ch: MeetingChannel): void {
    // A channel that the page dropped on purpose (or replaced) does not come back.
    if (ch !== this.channel) return;
    this.channel = null;
    const status = this.me()?.status;
    if (this.closed || (status !== 'pending' && status !== 'admitted')) return;
    this.attempts += 1;
    if (this.attempts > MAX_ATTEMPTS) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      // The state may have changed while the socket was gone.
      this.refresh();
      this.connect();
    }, RECONNECT_MS * this.attempts);
  }

  private disconnect(): void {
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const ch = this.channel;
    this.channel = null;
    ch?.close();
  }

  ngOnDestroy(): void {
    this.closed = true;
    if (this.refreshTimer !== null) clearTimeout(this.refreshTimer);
    this.disconnect();
  }
}
