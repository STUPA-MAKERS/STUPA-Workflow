import { Injectable } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import type { ClientMessage, ServerMessage } from './ws-messages';

/** Stellt eine offene Live-Vote-Verbindung dar (api.md §4). */
export interface MeetingChannel {
  /** Server→Client-Strom (JSON-Nachrichten). */
  messages$: Observable<ServerMessage>;
  /** Client→Server senden (cast/subscribe). */
  send(msg: ClientMessage): void;
  close(): void;
}

/**
 * WebSocket-Factory für Live-Vote-Kanäle. Auth via Session-Cookie beim
 * Handshake (same-origin). Reconnect-/Resilienz-Logik (subscribe-Resync) wird
 * vom Voting-Feature (T-32) auf dieser Basis aufgesetzt — hier nur das Gerüst.
 */
@Injectable({ providedIn: 'root' })
export class WsService {
  /** Öffnet `/api/ws/meetings/{id}` (oder `…/beamer` read-only). */
  connectMeeting(meetingId: string, beamer = false): MeetingChannel {
    const suffix = beamer ? '/beamer' : '';
    const ws = new WebSocket(this.url(`/api/ws/meetings/${meetingId}${suffix}`));
    const subject = new Subject<ServerMessage>();

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
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
      },
      close: () => ws.close(),
    };
  }

  /** Baut die ws(s)-URL relativ zum aktuellen Origin. */
  private url(path: string): string {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${window.location.host}${path}`;
  }
}
