import { InjectionToken, inject } from '@angular/core';
import { WsService, type MeetingChannel } from './ws.service';

/**
 * Quelle für Live-Vote-Kanäle (api.md §4). Abstrahiert das Öffnen eines
 * `MeetingChannel`, damit das Voting-Feature gegen die echte WebSocket
 * (`WsService` → T-16 `/api/ws/meetings/{id}[/beamer]`) **oder** gegen einen
 * In-Memory-Mock (Offline-/Dev-/Harness-Betrieb) laufen kann, ohne dass die
 * Components das unterscheiden.
 */
export interface LiveVoteSource {
  /** Öffnet `/api/ws/meetings/{id}` (oder `…/beamer` read-only). */
  connectMeeting(meetingId: string, beamer?: boolean): MeetingChannel;
}

/**
 * DI-Token für die Live-Vote-Quelle. Default = echte `WsService` (spricht den
 * T-16-Contract `/api/ws/meetings/{id}[/beamer]`, Auth via Session-Cookie beim
 * Handshake). Nur im Mock-Betrieb (`USE_MOCK_API`) wird in `app.config`
 * `MockLiveVoteSource` überschrieben — die Produktiv-/Integrationspfade laufen
 * gegen das echte Backend.
 */
export const LIVE_VOTE_SOURCE = new InjectionToken<LiveVoteSource>('LIVE_VOTE_SOURCE', {
  providedIn: 'root',
  factory: () => inject(WsService),
});
