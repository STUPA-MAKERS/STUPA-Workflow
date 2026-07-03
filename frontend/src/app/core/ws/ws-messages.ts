/** Live-vote WebSocket protocol. */

export interface MeetingStateMsg {
  type: 'meeting_state';
  activeApplicationId: string | null;
  status: string;
}
export interface VoteOpenedMsg {
  type: 'vote_opened';
  voteId: string;
  /** `null` = generic motion (free-text agenda item). */
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
  /** Participation progress + reveal gate. */
  cast?: number;
  present?: number;
  revealed?: boolean;
}
export interface VoteClosedMsg {
  type: 'vote_closed';
  voteId: string;
  result: string;
  counts: Record<string, number>;
  /** Reason for rejection: `quorum` = quorum missed, `majority` = majority missed. */
  failedReason?: 'quorum' | 'majority' | null;
}
/** Vote cancelled — no result, no branch. */
export interface VoteCancelledMsg {
  type: 'vote_cancelled';
  voteId: string;
}
export interface ErrorMsg {
  type: 'error';
  code: string;
}
/** Who currently has the meeting page open — display names. */
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
