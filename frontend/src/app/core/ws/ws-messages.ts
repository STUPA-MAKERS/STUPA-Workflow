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
  readonly type: 'meeting_state';
  readonly activeApplicationId: string | null;
  /** The agenda item the room handles now. Followers and the beamer follow it. */
  readonly currentAgendaItemId?: string | null;
  readonly status: string;
}
export interface VoteOpenedMsg {
  readonly type: 'vote_opened';
  readonly voteId: string;
  /** `null` means a generic motion, that is a free-text agenda item. */
  readonly applicationId?: string | null;
  readonly agendaItemId?: string | null;
  readonly question?: string | null;
  readonly options: readonly string[];
  readonly closesAt: string | null;
  /** A secret vote shows no interim tally. Older servers do not send it. */
  readonly secret?: boolean;
  /**
   * The server sent the vote as part of the state on a connect or a `subscribe`: the
   * vote was already open, it did not open now. Older servers do not send it.
   */
  readonly replay?: boolean;
  /** A personnel election carries its candidates and its round. */
  readonly kind?: VoteKind;
  readonly election?: ElectionConfig | null;
  readonly round?: number;
  /** A poll carries its mode and options. */
  readonly poll?: PollConfig | null;
}
export interface VoteTallyMsg {
  readonly type: 'vote_tally';
  readonly voteId: string;
  readonly counts: Record<string, number>;
  readonly eligible: number;
  readonly quorumMet: boolean;
  readonly leading: string | null;
  /** Participation progress and the reveal gate. */
  readonly cast?: number;
  readonly present?: number;
  readonly revealed?: boolean;
  /** Public meeting: the present members and the admitted guests, and whether guests vote. */
  readonly presentMembers?: number | null;
  readonly presentGuests?: number | null;
  readonly guestsVote?: boolean;
  readonly kind?: VoteKind;
  /** A poll: the counts with the order, once revealed. */
  readonly pollResult?: PollResult | null;
}
export interface VoteClosedMsg {
  readonly type: 'vote_closed';
  readonly voteId: string;
  /** `null` for a poll: a poll only counts. */
  readonly result: string | null;
  readonly counts: Record<string, number>;
  /** Rejection reason: `quorum` for a missed quorum, `majority` for a missed majority. */
  readonly failedReason?: 'quorum' | 'majority' | null;
  readonly kind?: VoteKind;
  /** The result of a personnel election. */
  readonly electionResult?: ElectionResult | null;
  /** The counts of a poll. */
  readonly pollResult?: PollResult | null;
}
/** The lot of a tied election was drawn: the room and the beamer show it. */
export interface VoteLotDrawnMsg {
  readonly type: 'vote_lot_drawn';
  readonly voteId: string;
  readonly result: VoteResult;
  readonly electionResult: ElectionResult;
}
/** A cancelled vote. It has no result and fires no branch. */
export interface VoteCancelledMsg {
  readonly type: 'vote_cancelled';
  readonly voteId: string;
}
/**
 * The text of an agenda item while the protokollant types it, before the autosave. The
 * voter channel carries it; the beamer and the guests never get it. `seq` rises per
 * editor session, so a viewer drops an older frame.
 */
export interface BodyDraftMsg {
  readonly type: 'body_draft';
  readonly agendaItemId: string;
  readonly body: string;
  readonly seq: number;
}
/**
 * The saved text or the done mark of an agenda item changed. The event names the item,
 * never the content: the page reads the agenda again. The guest channel sends it without
 * the item.
 */
export interface AgendaChangedMsg {
  readonly type: 'agenda_changed';
  readonly agendaItemId?: string;
}
export interface ErrorMsg {
  readonly type: 'error';
  readonly code: string;
}
/** The people who have the meeting page open now, by display name. */
export interface ViewersMsg {
  readonly type: 'viewers';
  readonly viewers: readonly string[];
}

/** Lead only: a new join request. */
export interface GuestRequestedMsg {
  readonly type: 'guest_requested';
  readonly guest: MeetingGuest;
}
/** Lead only: a request or a guest changed; status `expired` means the row is gone. */
export interface GuestUpdatedMsg {
  readonly type: 'guest_updated';
  readonly guest: MeetingGuest;
}
/** The public participation of the meeting changed. Members get no code and no pending count. */
export interface GuestCountsMsg {
  readonly type: 'guest_counts';
  readonly publicJoin?: boolean;
  readonly guestsMode?: GuestsMode;
  readonly joinCode?: string | null;
  readonly admittedGuests: number;
  readonly pendingGuests?: number;
}
/** Guest channel: the own status. After a final status the server closes the socket. */
export interface GuestStatusMsg {
  readonly type: 'guest_status';
  readonly status: GuestStatus | 'expired';
  readonly displayName: string | null;
  readonly number: number;
  readonly reason: 'public_off' | 'meeting_closed' | 'rotated' | null;
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
  | AgendaChangedMsg
  | ErrorMsg;

export type ClientMessage =
  | {
      readonly type: 'cast';
      readonly voteId: string;
      readonly choice: string | readonly string[] | Record<string, DateAnswer>;
      readonly asDelegation?: boolean;
    }
  | { readonly type: 'subscribe' }
  | BodyDraftMsg;

/**
 * A change ping of a board. It names what changed, never the content: the page reads the
 * card (`GET /todos/cards/{id}/tile`) or the board through REST, which keeps every rule.
 */
export type TodoPing =
  | { readonly type: 'card'; readonly boardId: string; readonly cardId: string }
  | { readonly type: 'card_removed'; readonly boardId: string; readonly cardId: string }
  | { readonly type: 'board'; readonly boardId: string };

/**
 * Server to client on the to-do channel. `closed` is not a server frame: the channel adds
 * it with the close code when the socket goes down.
 */
export type TodoServerMessage =
  | TodoPing
  | { readonly type: 'subscribed'; readonly boardIds: readonly string[] }
  | { readonly type: 'error'; readonly code: string }
  | { readonly type: 'closed'; readonly code: number };

/** Client to server on the to-do channel: the boards of the socket (it replaces the set). */
export interface TodoSubscribeMsg {
  readonly type: 'subscribe';
  readonly boardIds: readonly string[];
}
