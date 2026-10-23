import { render, screen } from '@testing-library/angular';
import { VoteProgressComponent } from './vote-progress.component';

async function setup(
  inputs: Partial<{ voted: number; total: number; basis: 'present' | 'eligible'; size: 'normal' | 'fat' }>,
) {
  return render(VoteProgressComponent, { inputs: { voted: 14, total: 19, ...inputs } });
}

describe('VoteProgressComponent', () => {
  it('shows the turnout of the present members, the percent and a bar', async () => {
    await setup({});
    expect(screen.getByText('14 von 19 Anwesenden haben abgestimmt')).toBeInTheDocument();
    expect(screen.getByText('74 %')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '14 von 19 Anwesenden haben abgestimmt' })).toBeInTheDocument();
  });

  it('shows no tally and no line about it while the vote runs', async () => {
    await setup({});
    expect(screen.queryByText(/Zwischenstand/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Ja|Nein|Enthaltung/)).not.toBeInTheDocument();
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

  it('draws the thick bar of the meeting vote card', async () => {
    const { fixture } = await setup({ size: 'fat' });
    expect(fixture.nativeElement).toHaveClass('vp--fat');
    expect(screen.getByRole('img', { name: '14 von 19 Anwesenden haben abgestimmt' })).toHaveClass('bar--fat');
  });
});
