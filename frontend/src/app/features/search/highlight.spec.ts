import { highlight } from './highlight';

describe('highlight', () => {
  it('marks every match regardless of case', () => {
    expect(highlight('Lastenrad im Radhaus', 'rad')).toEqual([
      { text: 'Lasten', hit: false },
      { text: 'rad', hit: true },
      { text: ' im ', hit: false },
      { text: 'Rad', hit: true },
      { text: 'haus', hit: false },
    ]);
  });

  it('gives the whole text as one plain part for an empty query or no match', () => {
    expect(highlight('Beamer', '  ')).toEqual([{ text: 'Beamer', hit: false }]);
    expect(highlight('Beamer', 'xyz')).toEqual([{ text: 'Beamer', hit: false }]);
  });

  it('marks a match at the start and at the end', () => {
    expect(highlight('förderung för', 'för')).toEqual([
      { text: 'för', hit: true },
      { text: 'derung ', hit: false },
      { text: 'för', hit: true },
    ]);
  });

  it('leaves a text plain when lowering it changes its length', () => {
    // "İ" lowers to two code units; the indexes would shift.
    expect(highlight('İstanbul', 'stan')).toEqual([{ text: 'İstanbul', hit: false }]);
  });
});
