import { applyRawFormat, insertRawInline, insertRawTable, insertRawTimeNote, protocolNow, rawKnownName } from './raw-format';

describe('applyRawFormat', () => {
  it('puts the blackout marks around the selection and takes them away again (000690)', () => {
    const on = applyRawFormat({ text: 'Es spricht Lena.', start: 11, end: 15 }, 'blackout');
    expect(on).toEqual({ text: 'Es spricht %%Lena%%.', start: 13, end: 17 });
    expect(applyRawFormat(on, 'blackout')).toEqual({ text: 'Es spricht Lena.', start: 11, end: 15 });
  });

  it('puts bold marks around the selection and takes them away again', () => {
    const on = applyRawFormat({ text: 'ein Wort hier', start: 4, end: 8 }, 'bold');
    expect(on).toEqual({ text: 'ein **Wort** hier', start: 6, end: 10 });
    expect(applyRawFormat(on, 'bold')).toEqual({ text: 'ein Wort hier', start: 4, end: 8 });
  });

  it('puts an empty pair at the cursor', () => {
    expect(applyRawFormat({ text: 'ab', start: 1, end: 1 }, 'italic')).toEqual({
      text: 'a**b',
      start: 2,
      end: 2,
    });
  });

  it('reads the inner star of a bold word as no italic mark', () => {
    const bold = { text: '**Wort**', start: 2, end: 6 };
    expect(applyRawFormat(bold, 'italic')).toEqual({ text: '***Wort***', start: 3, end: 7 });
    const italicBold = { text: '***Wort***', start: 3, end: 7 };
    expect(applyRawFormat(italicBold, 'italic')).toEqual({ text: '**Wort**', start: 2, end: 6 });
  });

  it('puts a heading prefix before the line and takes it away again', () => {
    const on = applyRawFormat({ text: 'eins\nzwei\ndrei', start: 7, end: 7 }, 'heading');
    expect(on).toEqual({ text: 'eins\n## zwei\ndrei', start: 10, end: 10 });
    expect(applyRawFormat(on, 'heading')).toEqual({ text: 'eins\nzwei\ndrei', start: 7, end: 7 });
  });

  it('makes every selected line a list item', () => {
    const on = applyRawFormat({ text: 'a\nb\nc', start: 0, end: 3 }, 'bulletList');
    expect(on).toEqual({ text: '- a\n- b\nc', start: 2, end: 7 });
    expect(applyRawFormat(on, 'bulletList')).toEqual({ text: 'a\nb\nc', start: 0, end: 3 });
  });

  it('adds the prefix when only some lines have it', () => {
    expect(applyRawFormat({ text: '- a\nb', start: 0, end: 5 }, 'bulletList').text).toBe('- - a\n- b');
  });
});

describe('insertRawTable', () => {
  const TABLE = '|  |  |  |\n| --- | --- | --- |\n|  |  |  |\n|  |  |  |';

  it('puts a table into an empty text with the cursor in the first cell', () => {
    expect(insertRawTable({ text: '', start: 0, end: 0 })).toEqual({ text: `${TABLE}\n`, start: 2, end: 2 });
  });

  it('separates the table from the text around it by an empty line', () => {
    const next = insertRawTable({ text: 'vorher\nnachher', start: 6, end: 6 }, 2, 1);
    expect(next.text).toBe('vorher\n\n|  |\n| --- |\n|  |\n\nnachher');
    expect(next.start).toBe(10);
  });

  it('adds no extra line where one is already', () => {
    const next = insertRawTable({ text: 'a\n\n\n\nb', start: 3, end: 3 }, 1, 1);
    expect(next.text).toBe('a\n\n|  |\n| --- |\n\nb');
    expect(insertRawTable({ text: 'a\n', start: 2, end: 2 }, 1, 1).text).toBe('a\n\n|  |\n| --- |\n');
    expect(insertRawTable({ text: 'a\nb', start: 1, end: 1 }, 1, 1).text).toBe('a\n\n|  |\n| --- |\n\nb');
  });
});

describe('insertRawTimeNote', () => {
  it('puts the note after the line of the caret and the caret at its end', () => {
    const text = 'Eins\nZwei\n\nDrei';
    const next = insertRawTimeNote({ text, start: 2, end: 2 }, '18:42');
    expect(next.text).toBe('Eins\n\n> [!anmerkung 18:42] \n\nZwei\n\nDrei');
    expect(next.text.slice(0, next.start).endsWith('18:42] ')).toBe(true);
  });

  it('writes the note alone into an empty text and at the end of a text', () => {
    expect(insertRawTimeNote({ text: '', start: 0, end: 0 }, '09:00').text).toBe('> [!anmerkung 09:00] ');
    expect(insertRawTimeNote({ text: 'A\n', start: 2, end: 2 }, '09:00').text).toBe('A\n\n> [!anmerkung 09:00] ');
    expect(insertRawTimeNote({ text: 'A\n\nB', start: 0, end: 0 }, '09:00').text).toBe(
      'A\n\n> [!anmerkung 09:00] \n\nB',
    );
  });
});

describe('protocolNow', () => {
  it('gives the time of Berlin with two digits', () => {
    expect(protocolNow(new Date('2026-11-13T08:05:00Z'))).toBe('09:05');
    expect(protocolNow(new Date('2026-07-01T22:30:00Z'))).toBe('00:30');
  });
});

describe('insertRawInline', () => {
  it('puts the reference at the caret with a space around it', () => {
    expect(insertRawInline({ text: 'Siehe Text', start: 5, end: 5 }, '[a](x)')).toEqual({
      text: 'Siehe [a](x) Text',
      start: 12,
      end: 12,
    });
    expect(insertRawInline({ text: '', start: 0, end: 0 }, '[a](x)').text).toBe('[a](x) ');
    expect(insertRawInline({ text: 'A weg B', start: 2, end: 5 }, '[a](x)').text).toBe('A [a](x) B');
  });
});

describe('applyRawFormat blackout block (000690, 000965)', () => {
  it('puts the fence lines around the lines of a selection over two paragraphs', () => {
    const text = 'Vorher\nErster\n\nZweiter\nDanach';
    const out = applyRawFormat({ text, start: 9, end: 20 }, 'blackout');
    expect(out.text).toBe('Vorher\n%%\nErster\n\nZweiter\n%%\nDanach');
    expect(out.text.slice(out.start, out.end)).toBe(text.slice(9, 20));
  });

  it('opens an empty block on an empty line', () => {
    const out = applyRawFormat({ text: 'A\n\nB', start: 2, end: 2 }, 'blackout');
    expect(out.text).toBe('A\n%%\n\n%%\nB');
  });

  it('removes the block that holds the caret', () => {
    const text = 'Vorher\n%%\nErster\n\nZweiter\n%%\nDanach';
    const out = applyRawFormat({ text, start: 12, end: 12 }, 'blackout');
    expect(out.text).toBe('Vorher\nErster\n\nZweiter\nDanach');
    expect(out.start).toBe(9);
  });

  it('keeps the inline mark in a block for its own selection', () => {
    const text = '%%\nEs spricht %%Lena%%.\n%%';
    const out = applyRawFormat({ text, start: 16, end: 20 }, 'blackout');
    expect(out.text).toBe('%%\nEs spricht Lena.\n%%');
  });
});

describe('applyRawFormat blackout block, edge cases (000690)', () => {
  const text = 'Vorher\n%%\nErster\n%%\nDanach';

  it('keeps a selection before the block and moves one after it', () => {
    const before = applyRawFormat({ text, start: 8, end: 8 }, 'blackout');
    expect(before.text).toBe('Vorher\nErster\nDanach');
    expect(before.start).toBe(7);
    const whole = applyRawFormat({ text, start: 7, end: 19 }, 'blackout');
    expect(whole.text).toBe('Vorher\nErster\nDanach');
    expect(whole.start).toBe(7);
    expect(whole.end).toBe(14);
  });

  it('takes a selection that ends on a line break as its lines only', () => {
    const out = applyRawFormat({ text: 'A\nB\nC', start: 0, end: 4 }, 'blackout');
    expect(out.text).toBe('%%\nA\nB\n%%\nC');
  });

  it('reads a %% line in code as code', () => {
    const code = '```\n%%\n```\nText';
    const out = applyRawFormat({ text: code, start: 11, end: 15 }, 'blackout');
    expect(out.text).toBe('```\n%%\n```\n%%Text%%');
  });
});

describe('rawKnownName (000969)', () => {
  const NAMES = [{ first: 'Lena', last: 'Hoffmann' }];
  const at = (text: string) => rawKnownName({ text, start: text.length, end: text.length }, NAMES);
  const marked = (text: string): string | null => {
    const m = at(text);
    return m ? text.slice(m.from, m.to) : null;
  };

  it('marks a known name in the line of the caret', () => {
    expect(marked('Vorher\nEs spricht Lena Hoffmann ')).toBe('Lena Hoffmann');
    expect(marked('Lena,')).toBe('Lena');
  });

  it('marks nothing in a marker, in code, in a block or with a selection', () => {
    expect(marked('%%Lena Hoffmann%% ')).toBeNull();
    expect(marked('%%offen Lena Hoffmann ')).toBeNull();
    expect(marked('`Lena Hoffmann` ')).toBeNull();
    expect(marked('```\nLena Hoffmann ')).toBeNull();
    expect(marked('%%\nLena Hoffmann \n%%'.slice(0, 17))).toBe('Lena Hoffmann');
    const block = '%%\nLena Hoffmann \n%%';
    expect(rawKnownName({ text: block, start: 17, end: 17 }, NAMES)).toBeNull();
    expect(rawKnownName({ text: 'Lena,', start: 0, end: 5 }, NAMES)).toBeNull();
    expect(rawKnownName({ text: '', start: 0, end: 0 }, NAMES)).toBeNull();
    expect(rawKnownName({ text: 'Lena,', start: 5, end: 5 }, [])).toBeNull();
  });
});
