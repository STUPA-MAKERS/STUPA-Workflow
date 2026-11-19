import { render } from '@testing-library/angular';
import type { PollDraft } from '../poll.util';
import { PollEditorComponent } from './poll-editor.component';

/** The date rows of a poll: Datum and Beginn are needed, and the end must lie after the start. */
describe('PollEditorComponent', () => {
  async function setup(draft: PollDraft) {
    const view = await render(PollEditorComponent, { inputs: { draft } });
    return view.fixture.componentInstance;
  }

  it('adds a date only with a date and a start and an end after the start', async () => {
    const editor = await setup({ mode: 'date', maxChoices: 2, options: [] });
    expect(editor.canAddDate()).toBe(false);
    editor.addDate();
    expect(editor.options()).toHaveLength(0);

    editor.newDate.set('2026-12-01');
    editor.newStart.set('18:00');
    editor.newEnd.set('17:00');
    expect(editor.endBeforeStart()).toBe(true);
    expect(editor.canAddDate()).toBe(false);

    editor.newEnd.set('20:00');
    expect(editor.endBeforeStart()).toBe(false);
    editor.addDate();
    expect(editor.options()).toEqual([
      { key: 1, label: '', date: '2026-12-01', start: '18:00', end: '20:00' },
    ]);
    expect(editor.newDate()).toBe('');

    editor.newDate.set('2026-12-02');
    editor.newEnd.set('');
    expect(editor.endBeforeStart()).toBe(false);
    expect(editor.canAddDate()).toBe(true);
  });

  it('keeps the text options apart from the dates', async () => {
    const editor = await setup({ mode: 'single', maxChoices: 2, options: [] });
    editor.newLabel.set('  Pizza ');
    editor.addLabel();
    editor.setMode('date');
    expect(editor.options()).toHaveLength(0);
    editor.setMode('nope');
    expect(editor.mode()).toBe('date');
    editor.setMode('single');
    expect(editor.options().map((o) => o.label)).toEqual(['Pizza']);
  });
});
