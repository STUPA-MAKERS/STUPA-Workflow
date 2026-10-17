import { applyRawFormat, insertRawTable } from './raw-format';

describe('applyRawFormat', () => {
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
