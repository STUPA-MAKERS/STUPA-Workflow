import type { ElectionConfig, ElectionResult } from '@core/api/models';
import type { TranslationKey } from '@core/i18n/translations';
import {
  abstentionsText,
  candidateName,
  electionBars,
  electionCaption,
  electionChoiceLabel,
  electionOf,
  electionResultLine,
  electionStatus,
  isYesNoElection,
  lotPending,
  runoffPending,
  seatsText,
} from './election.util';

/** A translate stub: the key with its parameters, so the tests read the shape. */
const t = (key: TranslationKey, params?: Record<string, string | number>) =>
  params ? `${key}${JSON.stringify(params)}` : key;

const ELECTION: ElectionConfig = {
  seats: 2,
  candidates: [
    { id: 'c1', name: 'Anna' },
    { id: 'c2', name: 'Ben' },
    { id: 'c3', name: 'Cem' },
  ],
  secret: true,
};
const SINGLE: ElectionConfig = { seats: 1, candidates: [{ id: 'c1', name: 'Anna' }], secret: true };

describe('election.util', () => {
  it('finds the election of a vote', () => {
    expect(electionOf(null)).toBeNull();
    expect(electionOf({ kind: 'motion' })).toBeNull();
    expect(electionOf({ kind: 'election' })).toBeNull();
    expect(electionOf({ kind: 'election', election: ELECTION })).toBe(ELECTION);
    expect(isYesNoElection(SINGLE)).toBe(true);
    expect(isYesNoElection(ELECTION)).toBe(false);
    expect(isYesNoElection(null)).toBe(false);
  });

  it('names candidates and ballots', () => {
    expect(candidateName(ELECTION, 'c2')).toBe('Ben');
    expect(candidateName(null, 'c9')).toBe('c9');
    expect(electionChoiceLabel(ELECTION, [], t)).toBe('vote.option.abstain');
    expect(electionChoiceLabel(ELECTION, ['c1', 'c2'], t)).toBe('Anna, Ben');
    expect(electionChoiceLabel(ELECTION, ['c1'], t)).toBe('Anna · election.abstentions.one');
    expect(electionChoiceLabel({ ...ELECTION, seats: 3 }, ['c1'], t)).toBe(
      'Anna · election.abstentions.other{"n":2}',
    );
    expect(electionChoiceLabel(null, ['c1'], t)).toBe('c1');
    expect(abstentionsText(1, t)).toBe('election.abstentions.one');
    expect(seatsText(1, t)).toBe('election.seats.one');
    expect(seatsText(4, t)).toBe('election.seats.other{"n":4}');
  });

  it('builds the bars best first with the tags and the abstentions', () => {
    const result: ElectionResult = {
      counts: { c1: 3, c2: 5, c3: 3 },
      abstentions: 1,
      ballots: 6,
      elected: ['c2'],
      runoff: { candidateIds: ['c1', 'c3'], seats: 1 },
    };
    const bars = electionBars(ELECTION, result, {}, t);
    expect(bars.map((b) => [b.id, b.count, b.elected, b.tied])).toEqual([
      ['c2', 5, true, false],
      ['c1', 3, false, true],
      ['c3', 3, false, true],
      ['abstain', 1, false, false],
    ]);
    // An open vote with revealed counts and no stored result.
    const open = electionBars(ELECTION, null, { c1: 1, abstain: 2 }, t);
    expect(open.find((b) => b.id === 'c1')?.count).toBe(1);
    expect(open.at(-1)).toMatchObject({ id: 'abstain', count: 2 });
    expect(electionBars(null, result, {}, t)).toEqual([]);
  });

  it('marks the candidates of a pending lot and builds the Ja/Nein bars', () => {
    const lot: ElectionResult = {
      counts: { c1: 2, c2: 2, c3: 0 },
      abstentions: 0,
      ballots: 4,
      elected: [],
      lot: { among: ['c1', 'c2'], seats: 1, drawn: null },
    };
    const bars = electionBars({ ...ELECTION, seats: 1 }, lot, {}, t);
    expect(bars.filter((b) => b.tied).map((b) => b.id)).toEqual(['c1', 'c2']);
    const yesNo = electionBars(
      SINGLE,
      { counts: { yes: 4, no: 1 }, abstentions: 2, ballots: 7, yes: 4, no: 1, elected: ['c1'] },
      { yes: 4, no: 1 },
      t,
    );
    expect(yesNo.map((b) => [b.id, b.count])).toEqual([
      ['yes', 4],
      ['no', 1],
      ['abstain', 2],
    ]);
  });

  it('tells the pending lot and runoff apart', () => {
    const er: ElectionResult = {
      counts: {},
      abstentions: 0,
      ballots: 0,
      elected: [],
      lot: { among: ['c1'], seats: 1, drawn: null },
      runoff: { candidateIds: ['c1'], seats: 1, voteId: null },
    };
    expect(lotPending('tie', er)).toBe(true);
    expect(lotPending('tie', { ...er, lot: { ...er.lot!, drawn: ['c1'] } })).toBe(false);
    expect(lotPending('elected', er)).toBe(false);
    expect(runoffPending('runoff', er)).toBe(true);
    expect(runoffPending('runoff', { ...er, runoff: { ...er.runoff!, voteId: 'v2' } })).toBe(false);
    expect(runoffPending('runoff', null)).toBe(false);
  });

  it('writes the result line, the caption and the status', () => {
    const er: ElectionResult = { counts: {}, abstentions: 0, ballots: 0, elected: ['c2', 'c1'] };
    expect(electionResultLine(ELECTION, 'elected', er, t)).toBe(
      'election.result.elected{"names":"Ben, Anna"}',
    );
    expect(electionResultLine(ELECTION, 'tie', er, t)).toBe('election.result.tie');
    expect(electionResultLine(ELECTION, 'rejected', er, t)).toBe('election.result.nobody');
    expect(electionResultLine(ELECTION, 'elected', null, t)).toBe('election.result.nobody');
    expect(electionCaption(ELECTION, 1, t)).toBe('election.kind · election.seats.other{"n":2}');
    expect(electionCaption(null, 2, t)).toBe('election.runoffRound{"n":2} · election.seats.one');
    expect(electionStatus('elected').kind).toBe('accent');
    expect(electionStatus('runoff').key).toBe('election.status.runoff');
    expect(electionStatus('tie').key).toBe('election.status.tie');
    expect(electionStatus('rejected').kind).toBe('error');
  });
});
