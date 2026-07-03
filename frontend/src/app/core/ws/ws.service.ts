import { Injectable, inject } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { LOCATION } from '../browser/location.token';
import type { ClientMessage, ServerMessage } from './ws-messages';

/** An open live-vote connection. */
export interface MeetingChannel {
  /** Server→client stream (JSON messages). */
  messages$: Observable<ServerMessage>;
  /** Send client→server (cast/subscribe). */
  send(msg: ClientMessage): void;
  close(): void;
}

/**
 * WebSocket factory for live-vote channels. Auth via session cookie at the
 * handshake (same-origin). Reconnect/resilience logic (subscribe resync) is
 * built on top of this by the voting feature — this is just the scaffolding.
 */
@Injectable({ providedIn: 'root' })
export class WsService {
  private readonly location = inject(LOCATION);

  /** Opens `/api/ws/meetings/{id}` (or `…/beamer` read-only). */
  connectMeeting(meetingId: string, beamer = false): MeetingChannel {
    const suffix = beamer ? '/beamer' : '';
    const ws = new WebSocket(this.url(`/api/ws/meetings/${meetingId}${suffix}`));
    const subject = new Subject<ServerMessage>();

    // Outbound buffer: frames sent before the handshake (`CONNECTING`) — e.g.
    // the LiveVoteSession's initial `subscribe` — would otherwise be dropped.
    // They are buffered and flushed in order on `open`.
    const outbox: string[] = [];
    const flush = (): void => {
      while (outbox.length > 0) ws.send(outbox.shift() as string);
    };

    ws.addEventListener('open', flush);
    ws.addEventListener('message', (ev: MessageEvent<string>) => {
      try {
        subject.next(JSON.parse(ev.data) as ServerMessage);
      } catch {
        subject.next({ type: 'error', code: 'malformed_message' });
      }
    });
    ws.addEventListener('error', () => subject.next({ type: 'error', code: 'socket_error' }));
    ws.addEventListener('close', () => subject.complete());

    return {
      messages$: subject.asObservable(),
      send: (msg: ClientMessage) => {
        const data = JSON.stringify(msg);
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data);
        } else if (ws.readyState === WebSocket.CONNECTING) {
          outbox.push(data); // buffer until `open`, then flush
        }
        // CLOSING/CLOSED → drop (a reconnect opens a new channel)
      },
      close: () => ws.close(),
    };
  }

  /** Builds the ws(s) URL relative to the current origin. */
  private url(path: string): string {
    const proto = this.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${this.location.host}${path}`;
  }
}
