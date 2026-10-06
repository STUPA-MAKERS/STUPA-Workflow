import type { GuestVote, Vote } from '@core/api/models';

/**
 * A vote of the guest view as the `Vote` of the shared vote panel. The panel then shows a
 * guest the same card, turnout, ballot and result as a member (#17). `meetingId` is set,
 * so the panel counts the turnout against the people present.
 */
export function guestVoteToVote(v: GuestVote): Vote {
  return {
    id: v.id,
    applicationId: null,
    meetingId: 'public',
    agendaItemId: v.agendaItemId,
    question: v.question,
    eligibleGroup: '',
    config: {
      options: v.options,
      majorityRule: v.majorityRule,
      quorum: v.quorum,
      secret: v.secret,
      guestsVote: v.guestsVote,
    },
    status: v.status,
    opensAt: v.openedAt,
    closesAt: null,
    result: v.result,
    secret: v.secret,
    majorityRule: v.majorityRule,
    quorum: v.quorum,
    openedAt: v.openedAt,
    closedAt: v.closedAt,
    guestsVote: v.guestsVote,
    tally: {
      counts: v.tally.counts,
      eligible: v.tally.present,
      quorumMet: true,
      leading: v.tally.leading,
      result: v.result,
      voted: v.tally.voted,
      present: v.tally.present,
      revealed: v.tally.revealed,
      failedReason: v.failedReason,
      presentMembers: v.tally.presentMembers,
      presentGuests: v.tally.presentGuests,
    },
    myBallot: v.myBallot,
  };
}
