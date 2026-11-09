import type { Vote } from '@core/api/models';
import type { TranslationKey } from '@core/i18n/translations';
import { voteChangeText, voteSubject } from './vote-announce.util';

const t = (key: TranslationKey, params?: Record<string, string | number>) =>
  params ? `${key}${JSON.stringify(params)}` : key;

const vote = (over: Partial<Vote> = {}): Vote => ({ id: 'v1', status: 'open', result: null, ...over }) as Vote;

describe('VoteAnnounce', () => {
  it('names the vote with its question, its meeting and its TOP', () => {
    expect(voteSubject(t, ' Haushalt ', '34. Sitzung', 3)).toBe(
      'Haushalt – voting.panel.where{"meeting":"34. Sitzung","n":3}',
    );
    expect(voteSubject(t, 'Haushalt', '34. Sitzung', null)).toBe('Haushalt – 34. Sitzung');
    expect(voteSubject(t, 'Haushalt', '34. Sitzung', undefined)).toBe('Haushalt – 34. Sitzung');
    expect(voteSubject(t, '  ', null, 3)).toBe('voting.live.vote');
    expect(voteSubject(t, undefined, undefined, undefined)).toBe('voting.live.vote');
  });

  it('tells an open and a close with its result', () => {
    expect(voteChangeText(t, { id: 'v1', status: 'draft' }, vote(), 'X')).toBe('voting.live.opened{"subject":"X"}');
    expect(voteChangeText(t, { id: 'v1', status: 'open' }, vote({ status: 'closed', result: 'passed' }), 'X')).toMatch(
      /^voting\.live\.closed\{"subject":"X","result":".+"\}$/,
    );
    expect(voteChangeText(t, { id: 'v1', status: 'open' }, vote({ status: 'closed' }), 'X')).toBe(
      'voting.live.closed{"subject":"X","result":""}',
    );
  });

  it('says nothing on a first read, another vote or any other change', () => {
    expect(voteChangeText(t, null, vote(), 'X')).toBe('');
    expect(voteChangeText(t, { id: 'v2', status: 'draft' }, vote(), 'X')).toBe('');
    expect(voteChangeText(t, { id: 'v1', status: 'open' }, vote(), 'X')).toBe('');
    expect(voteChangeText(t, { id: 'v1', status: 'open' }, vote({ status: 'cancelled' }), 'X')).toBe('');
    expect(voteChangeText(t, { id: 'v1', status: 'draft' }, vote({ status: 'closed' }), 'X')).toBe('');
  });
});
