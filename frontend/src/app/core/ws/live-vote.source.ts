import { InjectionToken, inject } from '@angular/core';
import { WsService, type MeetingChannel } from './ws.service';

/**
 * Source for live-vote channels. It abstracts the opening of a `MeetingChannel`. The
 * voting feature can then run against the real WebSocket (`WsService` at
 * `/api/ws/meetings/{id}[/beamer]`) or against an in-memory mock for offline, dev and
 * harness use. Components cannot tell the two apart.
 */
export interface LiveVoteSource {
  /** Open `/api/ws/meetings/{id}`, or `…/beamer` for read-only access. */
  connectMeeting(meetingId: string, beamer?: boolean): MeetingChannel;
}

/**
 * DI token for the live-vote source. The default is the real `WsService`. It speaks
 * `/api/ws/meetings/{id}[/beamer]` and authenticates with the session cookie at the
 * handshake. Only mock mode (`USE_MOCK_API`) puts `MockLiveVoteSource` in its place in
 * `app.config`. The production and integration paths run against the real backend.
 */
export const LIVE_VOTE_SOURCE = new InjectionToken<LiveVoteSource>('LIVE_VOTE_SOURCE', {
  providedIn: 'root',
  factory: () => inject(WsService),
});
