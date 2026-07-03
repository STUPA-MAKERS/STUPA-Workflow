import { InjectionToken, inject } from '@angular/core';
import { WsService, type MeetingChannel } from './ws.service';

/**
 * Source for live-vote channels. Abstracts opening a `MeetingChannel` so the
 * voting feature can run against the real WebSocket (`WsService` →
 * `/api/ws/meetings/{id}[/beamer]`) or against an in-memory mock
 * (offline/dev/harness) without components telling them apart.
 */
export interface LiveVoteSource {
  /** Opens `/api/ws/meetings/{id}` (or `…/beamer` read-only). */
  connectMeeting(meetingId: string, beamer?: boolean): MeetingChannel;
}

/**
 * DI token for the live-vote source. Default = the real `WsService` (speaks
 * `/api/ws/meetings/{id}[/beamer]`, auth via session cookie at the handshake).
 * Only in mock mode (`USE_MOCK_API`) is `MockLiveVoteSource` substituted in
 * `app.config` — the production/integration paths run against the real backend.
 */
export const LIVE_VOTE_SOURCE = new InjectionToken<LiveVoteSource>('LIVE_VOTE_SOURCE', {
  providedIn: 'root',
  factory: () => inject(WsService),
});
