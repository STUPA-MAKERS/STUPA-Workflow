import { render, screen } from '@testing-library/angular';
import type { PollConfig, PollResult } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { PollResultComponent } from './poll-result.component';

const SINGLE: PollConfig = {
  mode: 'single',
  options: [
    { id: 'o1', label: 'Pizza' },
    { id: 'o2', label: 'Pasta' },
    { id: 'o3', label: 'Salat' },
  ],
  secret: false,
};
const DATE: PollConfig = {
  mode: 'date',
  options: [
    { id: 'o1', start: '2026-11-03T17:00:00Z', end: '2026-11-03T19:00:00Z' },
    { id: 'o2', start: '2026-11-04T16:00:00Z' },
    { id: 'o3', start: '2026-11-05T16:00:00Z' },
  ],
  secret: false,
};

async function setup(inputs: {
  poll: PollConfig;
  result?: PollResult | null;
  counts?: Record<string, number>;
  answered?: number;
  total?: number;
}) {
  return render(PollResultComponent, { inputs: { answered: 0, total: 0, ...inputs } });
}

/** The labels of the rows, top to bottom (the tag included). */
function rows(): string[] {
  return screen.getAllByRole('listitem').map((li) => li.querySelector('.bars__label')!.textContent!.trim());
}

describe('PollResultComponent', () => {
  it('lists the options highest first and tags every tied top option', async () => {
    const result: PollResult = {
      counts: { o1: 4, o2: 1, o3: 4 },
      abstentions: 1,
      ballots: 10,
      order: ['o1', 'o3', 'o2'],
      top: ['o1', 'o3'],
    };
    const { container } = await setup({ poll: SINGLE, result, answered: 10, total: 12 });
    expect(rows()).toEqual([
      'Pizza meiste Stimmen',
      'Salat meiste Stimmen',
      'Pasta',
      'Enthaltungen',
    ]);
    expect(screen.getByText('Meiste Stimmen: Pizza, Salat')).toBeInTheDocument();
    expect(screen.getAllByText('40 %', { exact: false })).toHaveLength(2);
    expect(
      screen.getByText('10 von 12 haben geantwortet · Meinungsbild, kein Beschluss'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Zahl = Ja, (+n) = Vielleicht')).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('a date poll shows "3 (+2)", tags the best date and explains the numbers', async () => {
    const result: PollResult = {
      counts: { o1: 3, o2: 3, o3: 0 },
      maybe: { o1: 2 },
      abstentions: 0,
      ballots: 5,
      order: ['o1', 'o2', 'o3'],
      top: ['o1'],
    };
    await setup({ poll: DATE, result, answered: 5, total: 7 });
    const first = screen.getAllByRole('listitem')[0]!;
    expect(first.querySelector('.bars__count')!.textContent!.trim()).toBe('3');
    expect(first.querySelector('.bars__pct')!.textContent!.trim()).toBe('(+2)');
    expect(rows()[0]).toMatch(/03\.11\..*bester Termin$/);
    expect(rows()[1]).not.toMatch(/bester Termin/);
    // A date poll has no abstention row.
    expect(rows()).toHaveLength(3);
    expect(screen.getByText('Zahl = Ja, (+n) = Vielleicht')).toBeInTheDocument();
    expect(screen.getByText(/^Bester Termin: /)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /: 3 Ja, 2 Vielleicht/ })).toBeInTheDocument();
  });

  it('without a stored result ranks the revealed counts and names no top without a vote', async () => {
    const { fixture } = await setup({ poll: SINGLE, counts: { o2: 2, o3: 1, abstain: 1 } });
    expect(rows()).toEqual(['Pasta meiste Stimmen', 'Salat', 'Pizza', 'Enthaltungen']);
    fixture.componentRef.setInput('counts', {});
    fixture.detectChanges();
    expect(rows()).toEqual(['Pizza', 'Pasta', 'Salat', 'Enthaltungen']);
    expect(screen.queryByText(/Meiste Stimmen/)).toBeNull();
    expect(screen.getAllByText('0 %', { exact: false })).toHaveLength(4);
  });
});
