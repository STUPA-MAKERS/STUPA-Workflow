/** Live-vote WebSocket protocol. */

export interface MeetingStateMsg {
  type: 'meeting_state';
  activeApplicationId: string | null;
  /** The agenda item the room handles now. Followers and the beamer follow it. */
  currentAgendaItemId?: string | null;
  status: string;
}
export interface VoteOpenedMsg {
  type: 'vote_opened';
  voteId: string;
  /** `null` means a generic motion, that is a free-text agenda item. */
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
  /** Participation progress and the reveal gate. */
  cast?: number;
  present?: number;
  revealed?: boolean;
}
export interface VoteClosedMsg {
  type: 'vote_closed';
  voteId: string;
  result: string;
  counts: Record<string, number>;
  /** Rejection reason: `quorum` for a missed quorum, `majority` for a missed majority. */
  failedReason?: 'quorum' | 'majority' | null;
}
/** A cancelled vote. It has no result and fires no branch. */
export interface VoteCancelledMsg {
  type: 'vote_cancelled';
  voteId: string;
}
export interface ErrorMsg {
  type: 'error';
  code: string;
}
/** The people who have the meeting page open now, by display name. */
export interface ViewersMsg {
  type: 'viewers';
  viewers: string[];
}

export type ServerMessage =
  | MeetingStateMsg
  | VoteOpenedMsg
  | VoteTallyMsg
  | VoteClosedMsg
  | VoteCancelledMsg
  | ViewersMsg
  | ErrorMsg;

export type ClientMessage =
  | { type: 'cast'; voteId: string; choice: string }
  | { type: 'subscribe' };
