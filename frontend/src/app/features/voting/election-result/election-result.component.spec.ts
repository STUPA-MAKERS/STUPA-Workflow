import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { ElectionConfig, ElectionResult } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { ElectionResultComponent } from './election-result.component';

const ELECTION: ElectionConfig = {
  seats: 2,
  candidates: [
    { id: 'c1', name: 'Anna' },
    { id: 'c2', name: 'Ben' },
    { id: 'c3', name: 'Cem' },
    { id: 'c4', name: 'Dana' },
  ],
  secret: true,
};

const RUNOFF: ElectionResult = {
  counts: { c1: 6, c2: 3, c3: 3, c4: 1 },
  abstentions: 1,
  ballots: 7,
  elected: ['c1'],
  runoff: { candidateIds: ['c2', 'c3'], seats: 1, voteId: null },
};

async function setup(over: {
  result?: string | null;
  electionResult?: ElectionResult | null;
  canManage?: boolean;
  election?: ElectionConfig;
  counts?: Record<string, number>;
}) {
  const changed = jest.fn();
  const view = await render(ElectionResultComponent, {
    inputs: {
      election: over.election ?? ELECTION,
      result: over.result === undefined ? 'runoff' : over.result,
      electionResult: over.electionResult === undefined ? RUNOFF : over.electionResult,
      counts: over.counts ?? {},
      voteId: 'e1',
      canManage: over.canManage ?? true,
    },
    on: { changed },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, changed, toasts };
}

describe('ElectionResultComponent', () => {
  it('shows the bars best first with the tags and the runoff banner', async () => {
    const { container } = await setup({});
    expect(screen.getByText('Stichwahl nötig')).toBeInTheDocument();
    const labels = screen.getAllByRole('listitem').map((li) => li.querySelector('.bars__label')?.textContent?.trim());
    expect(labels).toEqual(['Anna gewählt', 'Ben Gleichstand', 'Cem Gleichstand', 'Dana', 'Enthaltungen']);
    expect(
      screen.getByText('Gleichstand an der Grenze: Stichwahl um 1 Posten zwischen Ben, Cem.'),
    ).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('starts the runoff: create, open, read', async () => {
    const { http, changed, toasts } = await setup({});
    await userEvent.click(screen.getByRole('button', { name: 'Stichwahl starten' }));
    http.expectOne({ method: 'POST', url: '/api/votes/e1/runoff' }).flush({ id: 'e2' });
    http.expectOne({ method: 'POST', url: '/api/votes/e2/open' }).flush(null);
    http.expectOne({ method: 'GET', url: '/api/votes/e2' }).flush({ id: 'e2', status: 'open' });
    expect(changed).toHaveBeenCalledWith({ id: 'e2', status: 'open' });
    expect(toasts()).toContain('Die Stichwahl ist offen.');
  });

  it('says the runoff exists and offers no second one', async () => {
    await setup({
      electionResult: { ...RUNOFF, runoff: { ...RUNOFF.runoff!, voteId: 'e2' } },
    });
    expect(screen.queryByRole('button', { name: 'Stichwahl starten' })).toBeNull();
    expect(screen.getByText('Die Stichwahl ist angelegt.')).toBeInTheDocument();
  });

  it('draws the lot of a tie; only a manager sees the button', async () => {
    const tie: ElectionResult = {
      counts: { c1: 2, c2: 2, c3: 0, c4: 0 },
      abstentions: 0,
      ballots: 4,
      elected: [],
      lot: { among: ['c1', 'c2'], seats: 1, drawn: null },
    };
    const { http, changed, toasts } = await setup({
      result: 'tie',
      electionResult: tie,
      election: { ...ELECTION, seats: 1 },
    });
    expect(screen.getByText('Gleichstand: das Los steht aus')).toBeInTheDocument();
    expect(screen.getByText('Gleichstand zwischen Anna, Ben. Das Los entscheidet.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Los ziehen' }));
    http.expectOne({ method: 'POST', url: '/api/votes/e1/draw-lot' }).flush({ id: 'e1' });
    expect(changed).toHaveBeenCalledWith({ id: 'e1' });
    expect(toasts()).toContain('Das Los ist gezogen.');
  });

  it('tells a member that the lead draws the lot, and shows a drawn lot', async () => {
    const lot = { among: ['c1', 'c2'], seats: 1, drawn: null };
    const tie: ElectionResult = { counts: { c1: 2, c2: 2 }, abstentions: 0, ballots: 4, elected: [], lot };
    const { fixture } = await setup({ result: 'tie', electionResult: tie, canManage: false });
    expect(screen.queryByRole('button', { name: 'Los ziehen' })).toBeNull();
    expect(screen.getByText('Die Sitzungsleitung zieht das Los.')).toBeInTheDocument();
    fixture.componentRef.setInput('result', 'elected');
    fixture.componentRef.setInput('electionResult', {
      ...tie,
      elected: ['c2'],
      lot: { ...lot, drawn: ['c2'] },
    });
    fixture.detectChanges();
    expect(screen.getByText('Gewählt: Ben')).toBeInTheDocument();
    expect(screen.getByText('Durch Los entschieden: Ben')).toBeInTheDocument();
  });

  it('reports a refused action and keeps the button', async () => {
    const tie: ElectionResult = {
      counts: {},
      abstentions: 0,
      ballots: 0,
      elected: [],
      lot: { among: ['c1', 'c2'], seats: 1, drawn: null },
    };
    const { http, toasts, changed, fixture } = await setup({ result: 'tie', electionResult: tie });
    await userEvent.click(screen.getByRole('button', { name: 'Los ziehen' }));
    http
      .expectOne('/api/votes/e1/draw-lot')
      .flush({ code: 'lot_already_drawn', detail: 'lot_already_drawn' }, { status: 409, statusText: 'Conflict' });
    expect(changed).not.toHaveBeenCalled();
    expect(toasts().some((m) => m.startsWith('Aktion fehlgeschlagen.'))).toBe(true);
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Los ziehen' })).toBeEnabled();
  });

  it('shows nobody elected, and the Ja/Nein bars of a single candidate', async () => {
    const { fixture } = await setup({
      result: 'rejected',
      electionResult: { counts: {}, abstentions: 0, ballots: 0, elected: [] },
    });
    expect(screen.getByText('Niemand gewählt')).toBeInTheDocument();
    fixture.componentRef.setInput('election', {
      seats: 1,
      candidates: [{ id: 'c1', name: 'Anna' }],
      secret: false,
    });
    fixture.componentRef.setInput('result', 'elected');
    fixture.componentRef.setInput('electionResult', {
      counts: { yes: 5, no: 1 },
      abstentions: 1,
      ballots: 7,
      yes: 5,
      no: 1,
      elected: ['c1'],
    });
    fixture.componentRef.setInput('counts', { yes: 5, no: 1, abstain: 1 });
    fixture.detectChanges();
    expect(screen.getByText('Gewählt: Anna')).toBeInTheDocument();
    expect(screen.getByLabelText('Ja: 5 Stimmen, 71 %')).toBeInTheDocument();
    expect(screen.getByLabelText('Nein: 1 Stimmen, 14 %')).toBeInTheDocument();
  });

  it('shows no status line while the vote is open', async () => {
    await setup({ result: null, electionResult: null, counts: { c1: 1 } });
    expect(screen.queryByText(/Gewählt|Stichwahl|Niemand/)).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
  });
});
