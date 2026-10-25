/** Live-vote WebSocket protocol. */

import type {
  DateAnswer,
  ElectionConfig,
  ElectionResult,
  GuestStatus,
  GuestsMode,
  MeetingGuest,
  PollConfig,
  PollResult,
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
  /** A personnel election carries its candidates and its round. */
  kind?: VoteKind;
  election?: ElectionConfig | null;
  round?: number;
  /** A poll carries its mode and options. */
  poll?: PollConfig | null;
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
  /** A poll: the counts with the order, once revealed. */
  pollResult?: PollResult | null;
}
export interface VoteClosedMsg {
  type: 'vote_closed';
  voteId: string;
  /** `null` for a poll: a poll only counts. */
  result: string | null;
  counts: Record<string, number>;
  /** Rejection reason: `quorum` for a missed quorum, `majority` for a missed majority. */
  failedReason?: 'quorum' | 'majority' | null;
  kind?: VoteKind;
  /** The result of a personnel election. */
  electionResult?: ElectionResult | null;
  /** The counts of a poll. */
  pollResult?: PollResult | null;
}
/** The lot of a tied election was drawn: the room and the beamer show it. */
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
/**
 * The text of an agenda item while the protokollant types it, before the autosave. The
 * voter channel carries it; the beamer and the guests never get it. `seq` rises per
 * editor session, so a viewer drops an older frame.
 */
export interface BodyDraftMsg {
  type: 'body_draft';
  agendaItemId: string;
  body: string;
  seq: number;
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
  | BodyDraftMsg
  | ErrorMsg;

export type ClientMessage =
  | {
      type: 'cast';
      voteId: string;
      choice: string | string[] | Record<string, DateAnswer>;
      asDelegation?: boolean;
    }
  | { type: 'subscribe' }
  | BodyDraftMsg;

// ------------------------------------------------------------------ to-do boards (`/api/ws/todos`)

/**
 * A change ping of a board. It names what changed, never the content: the page reads the
 * card (`GET /todos/cards/{id}/tile`) or the board through REST, which keeps every rule.
 */
export type TodoPing =
  | { type: 'card'; boardId: string; cardId: string }
  | { type: 'card_removed'; boardId: string; cardId: string }
  | { type: 'board'; boardId: string };

/**
 * Server to client on the to-do channel. `closed` is not a server frame: the channel adds
 * it with the close code when the socket goes down.
 */
export type TodoServerMessage =
  | TodoPing
  | { type: 'subscribed'; boardIds: string[] }
  | { type: 'error'; code: string }
  | { type: 'closed'; code: number };

/** Client to server on the to-do channel: the boards of the socket (it replaces the set). */
export interface TodoSubscribeMsg {
  type: 'subscribe';
  boardIds: string[];
}
