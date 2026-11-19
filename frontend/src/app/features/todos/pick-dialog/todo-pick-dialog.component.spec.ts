import { render } from '@testing-library/angular';
import { TodoPickDialogComponent } from './todo-pick-dialog.component';

async function setup(inputs: { pick?: string | null; busy?: boolean; rows?: { id: string; title: string; sub: string }[] } = {}) {
  const view = await render(TodoPickDialogComponent, {
    inputs: {
      open: true,
      heading: 'Wählen',
      listLabel: 'Liste',
      emptyHeading: 'Nichts da',
      submitLabel: 'Übernehmen',
      rows: inputs.rows ?? [{ id: 'r-1', title: 'Eins', sub: '' }],
      pick: inputs.pick ?? null,
      busy: inputs.busy ?? false,
    },
  });
  const cmp = view.fixture.componentInstance;
  const picked = jest.fn();
  cmp.picked.subscribe(picked);
  return { cmp, picked };
}

describe('TodoPickDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('hands on the picked row', async () => {
    const { cmp, picked } = await setup({ pick: 'r-1' });
    cmp.submit();
    expect(picked).toHaveBeenCalledWith('r-1');
  });

  it('hands on nothing without a pick', async () => {
    const { cmp, picked } = await setup();
    cmp.submit();
    expect(picked).not.toHaveBeenCalled();
  });

  it('hands on nothing while it works', async () => {
    const { cmp, picked } = await setup({ pick: 'r-1', busy: true });
    cmp.submit();
    expect(picked).not.toHaveBeenCalled();
  });

  it('lists the rows as select-sheet tiles with a check after the chosen one (001790)', async () => {
    await setup({
      pick: 'r-2',
      rows: [
        { id: 'r-1', title: 'Eins', sub: 'Mo., 23.11.' },
        { id: 'r-2', title: 'Zwei', sub: '' },
      ],
    });
    const list = document.querySelector('[role="radiogroup"]');
    expect(list?.classList).toContain('rowgroup--bg3');
    const rows = Array.from(document.querySelectorAll('[data-testid="pick-row"]'));
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.querySelector('.pd__check') !== null)).toEqual([false, true]);
    expect(rows[1].classList).toContain('pd__row--on');
    expect(document.querySelector('.pd__mark')).toBeNull();
  });

  it('closes on cancel', async () => {
    const { cmp } = await setup();
    cmp.cancel();
    expect(cmp.open()).toBe(false);
  });
});
