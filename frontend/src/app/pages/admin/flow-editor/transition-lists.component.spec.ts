import { render, screen } from '@testing-library/angular';
import type { TransitionLists } from './flow-editor.models';
import { TransitionListsComponent } from './transition-lists.component';

const LISTS: TransitionLists = {
  incoming: [{ index: 0, from: 'a', to: 'b', label: 'Einreichen', guard: 'Kein Guard (Catch-all)', automatic: false, branch: null }],
  outgoing: [
    { index: 1, from: 'b', to: 'c', label: '', guard: 'Frist abgelaufen', automatic: true, branch: null },
    { index: 2, from: 'b', to: 'd', label: 'Ablehnen', guard: 'Kein Guard (Catch-all)', automatic: false, branch: 'fail' },
  ],
};

describe('TransitionListsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists incoming then outgoing transitions with their counts and selects one on click', async () => {
    const view = await render(TransitionListsComponent, { inputs: { lists: LISTS } });
    const picked: number[] = [];
    view.fixture.componentInstance.selectTransition.subscribe((i) => picked.push(i));
    const headings = screen.getAllByRole('heading').map((h) => h.textContent?.trim());
    expect(headings).toEqual(['Eingehend (1)', 'Ausgehend (2)']);
    // Without a label the row names the states; an automatic row says so.
    screen.getByRole('button', { name: /^Automatisch: b → c/ }).click();
    screen.getByRole('button', { name: /^Ablehnen/ }).click();
    expect(picked).toEqual([1, 2]);
    // The branch shows between the states and the guard.
    expect(screen.getByRole('button', { name: /^Ablehnen/ }).textContent).toContain('fail');
  });

  it('says so when a list is empty', async () => {
    await render(TransitionListsComponent, {
      inputs: { lists: { incoming: [], outgoing: [] } },
    });
    expect(screen.getAllByText('Keine Übergänge.')).toHaveLength(2);
  });
});
