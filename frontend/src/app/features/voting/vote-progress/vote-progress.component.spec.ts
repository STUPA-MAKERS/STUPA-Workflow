import { render, screen } from '@testing-library/angular';
import { VoteProgressComponent } from './vote-progress.component';

async function setup(inputs: Partial<{ voted: number; total: number; basis: 'present' | 'eligible'; secret: boolean; hidden: boolean }>) {
  return render(VoteProgressComponent, { inputs: { voted: 14, total: 19, ...inputs } });
}

describe('VoteProgressComponent', () => {
  it('shows the turnout of the present members, the percent and a bar', async () => {
    await setup({});
    expect(screen.getByText('14 von 19 Anwesenden haben abgestimmt')).toBeInTheDocument();
    expect(screen.getByText('74 %')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '14 von 19 Anwesenden haben abgestimmt' })).toBeInTheDocument();
  });

  it('shows no tally while the vote runs, only the fixed line', async () => {
    await setup({});
    expect(
      screen.getByText('Zwischenstand sichtbar, sobald alle Anwesenden abgestimmt haben.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Ja|Nein|Enthaltung/)).not.toBeInTheDocument();
  });

  it('names the close for a secret vote', async () => {
    await setup({ secret: true });
    expect(
      screen.getByText('Geheime Abstimmung: Das Ergebnis zeigt sich nach dem Schließen.'),
    ).toBeInTheDocument();
  });

  it('drops the line once the server revealed the counts', async () => {
    await setup({ hidden: false });
    expect(screen.queryByText(/Zwischenstand/)).not.toBeInTheDocument();
  });

  it('counts a vote without a meeting against the eligible voters', async () => {
    await setup({ basis: 'eligible', voted: 3, total: 12 });
    expect(screen.getByText('3 von 12 Stimmberechtigten haben abgestimmt')).toBeInTheDocument();
    expect(screen.getByText('25 %')).toBeInTheDocument();
  });

  it('shows 0 % without anybody present and caps at 100 %', async () => {
    const { fixture } = await setup({ voted: 0, total: 0 });
    expect(screen.getByText('0 %')).toBeInTheDocument();
    fixture.componentRef.setInput('voted', 5);
    fixture.componentRef.setInput('total', 4);
    fixture.detectChanges();
    expect(screen.getByText('100 %')).toBeInTheDocument();
  });
});
