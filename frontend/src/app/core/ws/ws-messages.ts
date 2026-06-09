/** Live-Vote WebSocket-Protokoll (sds/api.md §4). */

export interface MeetingStateMsg {
  type: 'meeting_state';
  activeApplicationId: string | null;
  status: string;
}
export interface VoteOpenedMsg {
  type: 'vote_opened';
  voteId: string;
  /** `null` = generische Beschlussfrage (Freitext-TOP). */
  applicationId?: string | null;
  agendaItemId?: string | null;
  question?: string | null;
  options: string[];
  closesAt: string | null;
}
export interface VoteTallyMsg {
  type: 'vote_tally';
  voteId: string;
  counts: Record<string, number>;
  eligible: number;
  quorumMet: boolean;
  leading: string | null;
}
export interface VoteClosedMsg {
  type: 'vote_closed';
  voteId: string;
  result: string;
  counts: Record<string, number>;
}
export interface ErrorMsg {
  type: 'error';
  code: string;
}

export type ServerMessage =
  | MeetingStateMsg
  | VoteOpenedMsg
  | VoteTallyMsg
  | VoteClosedMsg
  | ErrorMsg;

export type ClientMessage =
  | { type: 'cast'; voteId: string; choice: string }
  | { type: 'subscribe' };
