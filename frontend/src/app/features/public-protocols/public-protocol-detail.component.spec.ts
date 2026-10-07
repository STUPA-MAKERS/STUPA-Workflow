import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import { of, throwError, type Observable } from 'rxjs';
import type { PublicProtocolDetail } from './public-protocols.models';
import { PublicProtocolDetailComponent } from './public-protocol-detail.component';
import { PublicProtocolsService } from './public-protocols.service';
import { detailFixture } from './public-protocols.fixtures';

async function setup(reply: Observable<PublicProtocolDetail> = of(detailFixture())) {
  const api = {
    detail: jest.fn(() => reply),
    pdfUrl: (id: string) => `/api/public/protocols/${id}/pdf`,
  };
  const view = await render(PublicProtocolDetailComponent, {
    providers: [
      provideRouter([]),
      { provide: PublicProtocolsService, useValue: api },
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: 'p-1' }) } } },
    ],
  });
  return { ...view, api };
}

describe('PublicProtocolDetailComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('shows the head, the PDF and the attendance as counts', async () => {
    const { api } = await setup();
    expect(api.detail).toHaveBeenCalledWith('p-1');
    expect(
      screen.getByRole('heading', { level: 1, name: '34. Sitzung des Studierendenparlaments' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Sitzung vom Di, 29.09.2026')).toBeInTheDocument();
    expect(screen.getByText('finalisiert am 02.10.2026')).toBeInTheDocument();
    const pdfs = screen.getAllByRole('link', { name: /PDF \(öffentliche Fassung\)/ });
    expect(pdfs).toHaveLength(2);
    expect(pdfs[0]).toHaveAttribute('href', '/api/public/protocols/p-1/pdf');
    expect(screen.getByText('PDF · 212 KB')).toBeInTheDocument();
    const att = screen.getByRole('heading', { name: 'Anwesenheit' }).closest('section') as HTMLElement;
    expect(att).toHaveTextContent('Anwesend23');
    expect(att).toHaveTextContent('Entschuldigt6');
    expect(att).toHaveTextContent('Abwesend2');
    expect(att).not.toHaveTextContent('Gäste');
    expect(screen.getByRole('link', { name: /Alle Protokolle: Studierendenparlament/ })).toHaveAttribute(
      'href',
      '/protokolle?gremium=g-1',
    );
  });

  it('renders the public text, the decisions and the non-public placeholder', async () => {
    await setup();
    const first = screen.getByRole('heading', { level: 3, name: /Begrüßung/ }).closest('li') as HTMLElement;
    expect(first.querySelector('strong')?.textContent).toBe('18:00');
    const second = screen.getByRole('heading', { level: 3, name: /Haushalt 2027/ }).closest('li') as HTMLElement;
    const [main, secret, open] = within(second).getAllByRole('figure');
    expect(main).toHaveTextContent('Soll der Haushalt beschlossen werden?');
    // Yes, no, abstain in this order.
    expect(main.textContent?.replace(/\s+/g, '')).toContain('Ja18Nein3Enthaltung2');
    expect(main).toHaveTextContent('Angenommen');
    expect(main).toHaveTextContent('Einfache Mehrheit · offene Abstimmung');
    expect(secret).toHaveTextContent('Abgelehnt');
    expect(secret).toHaveTextContent('Zweidrittelmehrheit · geheime Abstimmung');
    expect(open).not.toHaveTextContent('Ergebnis');
    expect(screen.getByRole('heading', { level: 3, name: /Nicht-öffentlicher Tagesordnungspunkt/ })).toBeInTheDocument();
    expect(screen.getByText('Titel, Inhalt und Beschlüsse sind nicht öffentlich.')).toBeInTheDocument();
    expect(screen.getByText('Ohne Text und ohne Beschluss.')).toBeInTheDocument();
  });

  it('names guests as a count and an unknown option as it is', async () => {
    const p = detailFixture({
      attendance: { present: 5, excused: 0, absent: 0, guests: 7 },
      pdfSize: null,
    });
    p.tops[1].decisions = [
      { question: 'Q', counts: { vielleicht: 1 }, result: 'tie', majorityRule: 'simple', secret: false },
    ];
    await setup(of(p));
    expect(screen.getByRole('heading', { name: 'Anwesenheit' }).closest('section')).toHaveTextContent('Gäste7');
    expect(screen.getByText('vielleicht')).toBeInTheDocument();
    expect(screen.getByText('Stimmengleichheit')).toBeInTheDocument();
    // A PDF without a known size shows no size line.
    expect(screen.queryByText(/^PDF ·/)).toBeNull();
  });

  it('shows the free text of a meeting without agenda items, and no PDF without one', async () => {
    await setup(
      of(
        detailFixture({
          tops: [],
          markdown: 'Nur **Freitext**.',
          hasPdf: false,
          pdfSize: null,
          finalizedAt: null,
        }),
      ),
    );
    expect(screen.getByText('Freitext').tagName).toBe('STRONG');
    expect(screen.queryByRole('link', { name: /PDF/ })).toBeNull();
    expect(screen.queryByText(/finalisiert am/)).toBeNull();
  });

  it('says when a protocol has no public text at all', async () => {
    await setup(of(detailFixture({ tops: [], markdown: null })));
    expect(screen.getByText(/keinen öffentlichen Text/)).toBeInTheDocument();
  });

  it('answers 404 with "not found" and a way back', async () => {
    await setup(throwError(() => new HttpErrorResponse({ status: 404 })));
    expect(screen.getByRole('heading', { name: 'Protokoll nicht gefunden' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Alle Protokolle/ })).toHaveAttribute('href', '/protokolle');
  });

  it('reports another failure as an error', async () => {
    await setup(throwError(() => new HttpErrorResponse({ status: 503 })));
    expect(screen.getByRole('alert')).toHaveTextContent('nicht geladen');
  });

  it('treats a failure without a status as not found', async () => {
    await setup(throwError(() => new Error('x')));
    expect(screen.getByRole('heading', { name: 'Protokoll nicht gefunden' })).toBeInTheDocument();
  });
});
