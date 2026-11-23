import type { ListRow, LoadState } from '@stupa-makers/ui-kit';
import { hitCount, listSearch, searchedRows, searchWords, textsMatch } from './list-search';

/** §002691: the search of a Verwaltung list finds the text of a row. */
describe('listSearch', () => {
  it('splits the search into lower-case words', () => {
    expect(searchWords('  Mika   MUSTER ')).toEqual(['mika', 'muster']);
    expect(searchWords('   ')).toEqual([]);
  });

  it('needs each word in one of the texts, without regard to case', () => {
    expect(textsMatch(['mika', 'vorstand'], ['Mika Muster', null, 'Vorstand'])).toBe(true);
    expect(textsMatch(['mika', 'kasse'], ['Mika Muster', undefined, 'Vorstand'])).toBe(false);
    expect(textsMatch([], [])).toBe(true);
  });

  it('filters items and keeps all without a search', () => {
    const s = listSearch();
    const items = [
      { name: 'StuPa', slug: 'stupa' },
      { name: 'AStA', slug: 'asta' },
    ];
    const texts = (i: (typeof items)[number]) => [i.name, i.slug];
    expect(s.filter(items, texts)).toHaveLength(2);
    s.set('ASTA');
    expect(s.text()).toBe('ASTA');
    expect(s.filter(items, texts)).toEqual([items[1]]);
    expect(s.matches(['nothing'])).toBe(false);
    s.set(null as unknown as string);
    expect(s.text()).toBe('');
  });

  it('turns an empty result of a search into "Keine Treffer" and counts the hits', () => {
    const s = listSearch();
    const empty: LoadState<readonly ListRow[]> = { state: 'empty', icon: 'users', heading: 'Leer' };
    const ready: LoadState<readonly ListRow[]> = { state: 'ready', data: [{ id: 'a', title: 'A' }] };
    const loading: LoadState<readonly ListRow[]> = { state: 'loading' };
    expect(searchedRows(empty, s, 'Keine Treffer.')).toBe(empty);
    expect(hitCount(ready, s)).toBeNull();
    s.set('x');
    expect(searchedRows(empty, s, 'Keine Treffer.')).toEqual({
      state: 'empty',
      icon: 'searchOff',
      heading: 'Keine Treffer.',
    });
    expect(searchedRows(ready, s, 'Keine Treffer.')).toBe(ready);
    expect(hitCount(ready, s)).toBe(1);
    expect(hitCount(empty, s)).toBe(0);
    expect(hitCount(loading, s)).toBeNull();
  });
});
