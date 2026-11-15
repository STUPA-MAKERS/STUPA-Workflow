import { castRefusalText } from './ballot-refusal';

const failure = (code: string) => ({
  asDelegation: true,
  alreadyVoted: false,
  error: { status: 409, error: { type: '', title: '', status: 409, code } },
});

describe('castRefusalText', () => {
  it('gives the own text of the two delegation refusals', () => {
    expect(castRefusalText(failure('vote_as_unit'))).toBe('voting.cast.toast.asUnit');
    expect(castRefusalText(failure('delegation_not_in_election'))).toBe(
      'voting.cast.toast.noDelegationInElection',
    );
  });

  it('gives null for each other code', () => {
    expect(castRefusalText(failure('vote_not_open'))).toBeNull();
    expect(castRefusalText({ asDelegation: false, alreadyVoted: false, error: {} })).toBeNull();
  });
});
