import { applyRawFormat } from './raw-format';

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
