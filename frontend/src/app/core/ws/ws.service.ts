import { Injectable, inject } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { LOCATION } from '../browser/location.token';
import type { ClientMessage, ServerMessage } from './ws-messages';

/** An open live-vote connection. */
export interface MeetingChannel {
  /** Stream of JSON messages from the server to the client. */
  messages$: Observable<ServerMessage>;
  /** Send a client to server frame, that is `cast` or `subscribe`. */
  send(msg: ClientMessage): void;
  close(): void;
}

/**
 * WebSocket factory for live-vote channels. The same-origin handshake authenticates
 * with the session cookie. The voting feature builds the reconnect and resync logic on
 * top of this class. This class is only the scaffolding.
 */
@Injectable({ providedIn: 'root' })
export class WsService {
  private readonly location = inject(LOCATION);

  /** Open `/api/ws/meetings/{id}`, or `…/beamer` for read-only access. */
  connectMeeting(meetingId: string, beamer = false): MeetingChannel {
    const suffix = beamer ? '/beamer' : '';
    const ws = new WebSocket(this.url(`/api/ws/meetings/${meetingId}${suffix}`));
    const subject = new Subject<ServerMessage>();

    // Outbound buffer. A socket drops a frame that goes out before the handshake ends
    // (`CONNECTING`), for example the initial `subscribe` of LiveVoteSession. The buffer
    // holds such a frame and flushes it in order on `open`.
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
          outbox.push(data);
        }
        // CLOSING or CLOSED: drop the frame. A reconnect opens a new channel.
      },
      close: () => ws.close(),
    };
  }

  /** Build the ws or wss URL relative to the current origin. */
  private url(path: string): string {
    const proto = this.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${this.location.host}${path}`;
  }
}
