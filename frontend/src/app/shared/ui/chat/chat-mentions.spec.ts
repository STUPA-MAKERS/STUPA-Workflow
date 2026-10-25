import {
  MentionPicker,
  chatPeople,
  highlightMentions,
  insertMention,
  matchPeople,
  mentionIds,
  mentionQuery,
  type ChatPerson,
} from './chat-mentions';

const PEOPLE: ChatPerson[] = [
  { principalId: 'p-1', displayName: 'Jonas Weber' },
  { principalId: 'p-2', displayName: 'Selin Yıldız' },
  { principalId: 'p-3', displayName: 'Anna' },
  { principalId: 'p-4', displayName: 'Anna Maria Krüger' },
  { principalId: 'p-5', displayName: 'Lena Ahrens' },
];

function key(k: string, extra: Partial<KeyboardEventInit> = {}): KeyboardEvent {
  return new KeyboardEvent('keydown', { key: k, ...extra });
}

describe('chat mentions', () => {
  it('keeps only the people with an id and a name', () => {
    expect(
      chatPeople([
        { principalId: 'p-1', displayName: 'Jonas' },
        { principalId: null, displayName: 'Gelöscht' },
        { principalId: 'p-2', displayName: null },
      ]),
    ).toEqual([{ principalId: 'p-1', displayName: 'Jonas' }]);
    expect(chatPeople(null)).toEqual([]);
    expect(chatPeople(undefined)).toEqual([]);
  });

  describe('mentionQuery', () => {
    /** The caret decides, not the end of the text. */
    it('finds the "@" search before the caret at the start of a word', () => {
      expect(mentionQuery('@', 1)).toEqual({ start: 0, query: '' });
      expect(mentionQuery('Hallo @Jo', 9)).toEqual({ start: 6, query: 'Jo' });
      expect(mentionQuery('(@Jo', 4)).toEqual({ start: 1, query: 'Jo' });
      expect(mentionQuery('@Anna Ma', 8)).toEqual({ start: 0, query: 'Anna Ma' });
      expect(mentionQuery('@Jo und mehr', 3)).toEqual({ start: 0, query: 'Jo' });
    });

    it('opens no search in an address, after a line break, a space or a second "@"', () => {
      expect(mentionQuery('kein @', 0)).toBeNull();
      expect(mentionQuery('mail@example.org', 16)).toBeNull();
      expect(mentionQuery('@Jo\nnein', 8)).toBeNull();
      expect(mentionQuery('@ Jo', 4)).toBeNull();
      expect(mentionQuery(`@${'x'.repeat(41)}`, 42)).toBeNull();
      expect(mentionQuery('text', 4)).toBeNull();
    });
  });

  describe('matchPeople', () => {
    it('puts names that start with the search first, then a later word, then a part', () => {
      expect(matchPeople(PEOPLE, 'a').map((p) => p.principalId)).toEqual(['p-3', 'p-4', 'p-5']);
      expect(matchPeople(PEOPLE, 'en').map((p) => p.principalId)).toEqual(['p-5']);
      expect(matchPeople(PEOPLE, 'we').map((p) => p.principalId)).toEqual(['p-1']);
      expect(matchPeople(PEOPLE, 'rüg').map((p) => p.principalId)).toEqual(['p-4']);
    });

    /** One letter matches only the start of a word, not the middle. */
    it('ignores case and accents and caps the list', () => {
      expect(matchPeople(PEOPLE, 'yil').map((p) => p.principalId)).toEqual(['p-2']);
      expect(matchPeople(PEOPLE, 'YILDIZ').map((p) => p.principalId)).toEqual(['p-2']);
      expect(matchPeople(PEOPLE, 'kruger').map((p) => p.principalId)).toEqual(['p-4']);
      expect(matchPeople(PEOPLE, '')).toHaveLength(5);
      expect(matchPeople(PEOPLE, '', 2)).toHaveLength(2);
      expect(matchPeople(PEOPLE, 'z')).toEqual([]);
    });

    it('sorts equal ranks by name, then by id', () => {
      const twins = [
        { principalId: 'b', displayName: 'Kim' },
        { principalId: 'a', displayName: 'Kim' },
      ];
      expect(matchPeople(twins, 'k').map((p) => p.principalId)).toEqual(['a', 'b']);
    });
  });

  it('puts "@Name " in place of the search and moves the caret after it', () => {
    expect(insertMention('Hallo @jo', 6, 9, 'Jonas Weber')).toEqual({
      text: 'Hallo @Jonas Weber ',
      caret: 19,
    });
    expect(insertMention('@jo und', 0, 3, 'Jonas')).toEqual({ text: '@Jonas und', caret: 7 });
    expect(insertMention('@jo,', 0, 3, 'Jonas')).toEqual({ text: '@Jonas ,', caret: 7 });
  });

  describe('mentionIds', () => {
    it('finds the named people in the order of the text, each once', () => {
      expect(mentionIds('@Selin Yıldız und @Jonas Weber, danke @Selin Yıldız', PEOPLE)).toEqual([
        'p-2',
        'p-1',
      ]);
      expect(mentionIds('Hallo', PEOPLE)).toEqual([]);
    });

    it('takes the longer name where two start alike, and needs a word boundary', () => {
      expect(mentionIds('@Anna Maria Krüger', PEOPLE)).toEqual(['p-4']);
      expect(mentionIds('@Anna und @Anna Maria Krüger', PEOPLE)).toEqual(['p-3', 'p-4']);
      expect(mentionIds('@Annabell', PEOPLE)).toEqual([]);
      expect(mentionIds('mail@Anna', PEOPLE)).toEqual([]);
      expect(mentionIds('(@Anna)', PEOPLE)).toEqual(['p-3']);
    });

    it('takes the chosen person of two with the same name, else the first', () => {
      const twins = [
        { principalId: 'k-1', displayName: 'Kim' },
        { principalId: 'k-2', displayName: 'Kim' },
      ];
      expect(mentionIds('@Kim', twins)).toEqual(['k-1']);
      expect(mentionIds('@Kim', twins, ['k-2'])).toEqual(['k-2']);
    });
  });

  describe('highlightMentions', () => {
    it('marks the names in text, not in links or code', () => {
      expect(highlightMentions('<p>Hallo @Jonas Weber!</p>', ['Jonas Weber'])).toBe(
        '<p>Hallo <span class="chat__mention">@Jonas Weber</span>!</p>',
      );
      expect(highlightMentions('<code>@Jonas</code> <a href="x">@Jonas</a>', ['Jonas'])).toBe(
        '<code>@Jonas</code> <a href="x">@Jonas</a>',
      );
      expect(highlightMentions('@Jonas @Jonasx', ['Jonas'])).toBe(
        '<span class="chat__mention">@Jonas</span> @Jonasx',
      );
    });

    it('matches the escaped form of a name and the longer name first', () => {
      expect(highlightMentions('@A &amp; B', ['A & B'])).toBe(
        '<span class="chat__mention">@A &amp; B</span>',
      );
      expect(highlightMentions('@Jo O&#39;Neil', ["Jo O'Neil"])).toBe(
        '<span class="chat__mention">@Jo O&#39;Neil</span>',
      );
      expect(highlightMentions('@Anna Maria', ['Anna', 'Anna Maria'])).toBe(
        '<span class="chat__mention">@Anna Maria</span>',
      );
      expect(highlightMentions('<p>@Jo</p>', ['  ', 'Jo', 'Jo'])).toBe(
        '<p><span class="chat__mention">@Jo</span></p>',
      );
    });

    it('leaves the text alone without names', () => {
      expect(highlightMentions('<p>@Jo</p>', [])).toBe('<p>@Jo</p>');
    });
  });

  describe('MentionPicker', () => {
    function picker(people = PEOPLE): MentionPicker {
      const p = new MentionPicker('m');
      p.setPeople(people);
      return p;
    }

    it('opens on a search with matches and names its options', () => {
      const p = picker();
      p.update('Hallo @an', 9);
      expect(p.open()).toBe(true);
      expect(p.options().map((o) => o.principalId)).toEqual(['p-3', 'p-4']);
      expect(p.optionId(1)).toBe('m-1');
      p.update('Hallo @xyz', 10);
      expect(p.open()).toBe(false);
    });

    it('stays closed without people', () => {
      const p = picker([]);
      p.update('@a', 2);
      expect(p.open()).toBe(false);
    });

    /** The same search keeps the row; a new one starts at the top. */
    it('moves with the arrows, wraps around and starts again on a new search', () => {
      const p = picker();
      p.update('@a', 2);
      expect(p.key(key('ArrowDown'))).toBe('handled');
      expect(p.key(key('ArrowDown'))).toBe('handled');
      expect(p.active()).toBe(2);
      p.key(key('ArrowDown'));
      expect(p.active()).toBe(0);
      p.key(key('ArrowUp'));
      expect(p.active()).toBe(2);
      p.update('@a', 2);
      expect(p.active()).toBe(2);
      p.update('@ann', 4);
      expect(p.active()).toBe(0);
    });

    it('takes the active person with Enter or Tab, and lets other keys through', () => {
      const p = picker();
      p.update('@an', 3);
      p.key(key('ArrowDown'));
      expect(p.key(key('Enter'))).toEqual(PEOPLE[3]);
      expect(p.key(key('Tab'))).toEqual(PEOPLE[3]);
      expect(p.key(key('Enter', { shiftKey: true }))).toBeNull();
      expect(p.key(key('a'))).toBeNull();
      expect(p.key(key('Enter', { isComposing: true }))).toBeNull();
    });

    it('lets every key through while closed', () => {
      const p = picker();
      expect(p.key(key('Enter'))).toBeNull();
    });

    it('puts the person into the text and closes', () => {
      const p = picker();
      p.update('Hi @jo', 6);
      expect(p.apply('Hi @jo', PEOPLE[0])).toEqual({ text: 'Hi @Jonas Weber ', caret: 16 });
      expect(p.open()).toBe(false);
      expect(p.apply('Hi', PEOPLE[0])).toBeNull();
      expect(p.picked()).toEqual(['p-1']);
      p.update('Hi @Jonas Weber @jo', 19);
      p.apply('Hi @Jonas Weber @jo', PEOPLE[0]);
      expect(p.picked()).toEqual(['p-1']);
      p.reset(['p-2']);
      expect(p.picked()).toEqual(['p-2']);
      p.reset();
      expect(p.picked()).toEqual([]);
    });

    /** "Anna" is a whole name, so the list closes after it. */
    it('treats "@Name " after a whole name as done, and "@Anna " as a search for more', () => {
      const p = picker();
      p.update('@Jonas Weber ', 13);
      expect(p.open()).toBe(false);
      p.update('@Anna ', 6);
      expect(p.open()).toBe(false);
      p.update('@Selin ', 7);
      expect(p.options().map((o) => o.principalId)).toEqual(['p-2']);
    });

    it('stays closed after Escape for this "@" and opens again at the next one', () => {
      const p = picker();
      p.update('@an', 3);
      expect(p.key(key('Escape'))).toBe('handled');
      expect(p.open()).toBe(false);
      p.update('@ann', 4);
      expect(p.open()).toBe(false);
      p.update('@ann @jo', 8);
      expect(p.open()).toBe(true);
      p.update('', 0);
      p.update('@an', 3);
      expect(p.open()).toBe(true);
    });
  });
});
