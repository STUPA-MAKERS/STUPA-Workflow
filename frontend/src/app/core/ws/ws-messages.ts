/** Live-vote WebSocket protocol. */

import type {
  ElectionConfig,
  ElectionResult,
  GuestStatus,
  GuestsMode,
  MeetingGuest,
  VoteKind,
  VoteResult,
} from '../api/models';


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
  /** A secret vote shows no interim tally. Older servers do not send it. */
  secret?: boolean;
  /**
   * The server sent the vote as part of the state on a connect or a `subscribe`: the
   * vote was already open, it did not open now. Older servers do not send it.
   */
  replay?: boolean;
  /** A personnel election (F2) carries its candidates and its round. */
  kind?: VoteKind;
  election?: ElectionConfig | null;
  round?: number;
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
  /** Public meeting: the present members and the admitted guests, and whether guests vote. */
  presentMembers?: number | null;
  presentGuests?: number | null;
  guestsVote?: boolean;
  kind?: VoteKind;
}
export interface VoteClosedMsg {
  type: 'vote_closed';
  voteId: string;
  result: string;
  counts: Record<string, number>;
  /** Rejection reason: `quorum` for a missed quorum, `majority` for a missed majority. */
  failedReason?: 'quorum' | 'majority' | null;
  kind?: VoteKind;
  /** The result of a personnel election (F2). */
  electionResult?: ElectionResult | null;
}
/** The lot of a tied election was drawn (F2): the room and the beamer show it. */
export interface VoteLotDrawnMsg {
  type: 'vote_lot_drawn';
  voteId: string;
  result: VoteResult;
  electionResult: ElectionResult;
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

/** Lead only: a new join request. */
export interface GuestRequestedMsg {
  type: 'guest_requested';
  guest: MeetingGuest;
}
/** Lead only: a request or a guest changed; status `expired` means the row is gone. */
export interface GuestUpdatedMsg {
  type: 'guest_updated';
  guest: MeetingGuest;
}
/** The public participation of the meeting changed. Members get no code and no pending count. */
export interface GuestCountsMsg {
  type: 'guest_counts';
  publicJoin?: boolean;
  guestsMode?: GuestsMode;
  joinCode?: string | null;
  admittedGuests: number;
  pendingGuests?: number;
}
/** Guest channel: the own status. After a final status the server closes the socket. */
export interface GuestStatusMsg {
  type: 'guest_status';
  status: GuestStatus | 'expired';
  displayName: string | null;
  number: number;
  reason: 'public_off' | 'meeting_closed' | 'rotated' | null;
}

export type ServerMessage =
  | GuestRequestedMsg
  | GuestUpdatedMsg
  | GuestCountsMsg
  | GuestStatusMsg
  | MeetingStateMsg
  | VoteOpenedMsg
  | VoteTallyMsg
  | VoteClosedMsg
  | VoteLotDrawnMsg
  | VoteCancelledMsg
  | ViewersMsg
  | ErrorMsg;

export type ClientMessage =
  | { type: 'cast'; voteId: string; choice: string | string[]; asDelegation?: boolean }
  | { type: 'subscribe' };
