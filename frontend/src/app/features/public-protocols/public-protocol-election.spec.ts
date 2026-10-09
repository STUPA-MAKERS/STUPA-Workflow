import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { of } from 'rxjs';
import type { PublicDecision, PublicProtocolDetail } from './public-protocols.models';
import { PublicProtocolDetailComponent } from './public-protocol-detail.component';
import { PublicProtocolsService } from './public-protocols.service';
import { detailFixture } from './public-protocols.fixtures';

/** The fixture with one election decision on its second item (F2). */
function withElection(decision: PublicDecision): PublicProtocolDetail {
  const detail = detailFixture();
  return {
    ...detail,
    tops: detail.tops.map((top, i) => (i === 1 ? { ...top, decisions: [decision] } : top)),
  };
}

async function setup(decision: PublicDecision) {
  const api = { detail: jest.fn(() => of(withElection(decision))), pdfUrl: () => '/pdf' };
  return render(PublicProtocolDetailComponent, {
    providers: [
      provideRouter([]),
      { provide: PublicProtocolsService, useValue: api },
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: 'p-1' }) } } },
    ],
  });
}

describe('PublicProtocolDetailComponent · election (F2)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('names the elected persons only and counts the others', async () => {
    await setup({
      question: 'Wahl der Referate',
      counts: {},
      result: 'elected',
      majorityRule: 'simple',
      secret: true,
      kind: 'election',
      seats: 2,
      round: 2,
      elected: ['Anna', 'Ben'],
      otherCandidates: 2,
      byLot: true,
    });
    const figure = screen.getByText('Wahl der Referate').closest('figure') as HTMLElement;
    expect(figure).toHaveTextContent('Stichwahl (2. Wahlgang) · 2 Posten · geheime Abstimmung');
    expect(figure).toHaveTextContent('Gewählt: Anna, Ben');
    expect(figure).toHaveTextContent('2 weitere Kandidierende');
    expect(figure).toHaveTextContent('Durch Los entschieden.');
    expect(figure).not.toHaveTextContent('Einfache Mehrheit');
  });

  it('says nobody was elected', async () => {
    await setup({
      question: 'Wahl der Kasse',
      counts: {},
      result: 'rejected',
      majorityRule: 'simple',
      secret: false,
      kind: 'election',
      seats: null,
      elected: [],
      otherCandidates: 0,
    });
    const figure = screen.getByText('Wahl der Kasse').closest('figure') as HTMLElement;
    expect(figure).toHaveTextContent('Wahl · 1 Posten · offene Abstimmung');
    expect(figure).toHaveTextContent('Niemand gewählt');
    expect(figure).not.toHaveTextContent('weitere');
    expect(figure).not.toHaveTextContent('Los');
  });
});
