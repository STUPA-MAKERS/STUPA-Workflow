import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../testing/a11y';
import { VoteBarsComponent } from './vote-bars.component';

const OPTIONS = ['yes', 'no', 'abstain'];

async function setup(inputs: Record<string, unknown> = {}) {
  return render(VoteBarsComponent, {
    inputs: { options: OPTIONS, counts: { yes: 15, no: 3, abstain: 2 }, ...inputs },
  });
}

describe('VoteBarsComponent', () => {
  it('shows one row per option with count and share of the cast ballots', async () => {
    await setup();
    expect(screen.getByText('Ja')).toBeInTheDocument();
    expect(screen.getByText('15')).toBeInTheDocument();
    expect(screen.getByText('75 %')).toBeInTheDocument();
    expect(screen.getByText('15 %')).toBeInTheDocument();
    expect(screen.getByText('10 %')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Ja: 15 Stimmen, 75 %' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Ergebnis, 20 Stimmen' })).toBeInTheDocument();
  });

  it('draws Ja in the accent, Nein in the error colour and Enthaltung grey', async () => {
    const { container } = await setup();
    const segs = [...container.querySelectorAll('app-seg-bar')].map(
      (bar) => bar.querySelector('.bar__seg')?.className ?? '',
    );
    expect(segs[0]).toContain('bar__seg--filled');
    expect(segs[1]).toContain('bar__seg--error');
    expect(segs[2]).toContain('bar__seg--muted');
  });

  it('shows no status line without a result', async () => {
    await setup();
    expect(screen.queryByText(/Angenommen|Abgelehnt/)).not.toBeInTheDocument();
  });

  it('shows Angenommen for a passed vote', async () => {
    await setup({ result: 'passed' });
    expect(screen.getByText('Angenommen')).toHaveClass('st--accent');
  });

  it('shows a tie as Abgelehnt (O18)', async () => {
    await setup({ result: 'tie', counts: { yes: 4, no: 4, abstain: 1 } });
    expect(screen.getByText('Abgelehnt')).toHaveClass('st--error');
    expect(screen.queryByText(/Stimmengleichheit/)).not.toBeInTheDocument();
  });

  it('adds the missed quorum to a rejection', async () => {
    await setup({ result: 'rejected', failedReason: 'quorum' });
    expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
    expect(screen.getByText('Quorum nicht erreicht')).toBeInTheDocument();
  });

  it('shows zero shares and a grey bar without any ballot', async () => {
    const { container } = await setup({ counts: {} });
    expect(screen.getAllByText('0 %')).toHaveLength(3);
    expect(container.querySelectorAll('.bar__rest')).toHaveLength(3);
  });

  it('keeps an unknown option as its raw key in the accent', async () => {
    const { container } = await setup({ options: ['maybe'], counts: { maybe: 1 } });
    expect(screen.getByText('maybe')).toBeInTheDocument();
    expect(container.querySelector('.bar__seg')?.className).toContain('bar__seg--filled');
  });

  it('switches to the beamer variant', async () => {
    const { fixture } = await setup({ variant: 'beamer' });
    expect(fixture.nativeElement).toHaveClass('bars--beamer');
  });

  it('has no a11y violations', async () => {
    const { container } = await setup({ result: 'passed' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
