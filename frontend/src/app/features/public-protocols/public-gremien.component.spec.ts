import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import { Meta } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import type { PublicGremium } from './public-protocols.models';
import { PublicGremienComponent } from './public-gremien.component';
import { PublicProtocolsService } from './public-protocols.service';

const GREMIEN = [
  { id: 'g-2', name: 'AStA', slug: 'asta', protocolCount: 7, latestDate: '2026-07-14' },
  { id: 'g-1', name: 'Studierendenparlament', slug: 'stupa', protocolCount: 8, latestDate: '2026-09-29' },
];

function makeApi(over: Record<string, jest.Mock> = {}) {
  return { gremien: jest.fn(() => of(GREMIEN)), ...over };
}

async function setup(
  kind: 'protocols' | 'decisions' | undefined = 'protocols',
  api = makeApi(),
  committee: readonly string[] = [],
) {
  const view = await render(PublicGremienComponent, {
    providers: [
      provideRouter([]),
      { provide: PublicProtocolsService, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: {
            data: kind ? { kind } : {},
            queryParamMap: convertToParamMap({ committee: [...committee] }),
          },
        },
      },
    ],
  });
  return { ...view, api };
}

describe('PublicGremienComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  /** Spec 002400: one row per public Gremium, with the day of its newest protocol and no count. */
  it('lists the public gremien of the protocols with the day of the newest protocol', async () => {
    await setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Öffentliche Protokolle' })).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Gremien' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole('link', { name: /AStA/ })).toHaveAttribute('href', '/protocols/asta');
    expect(within(rows[1]).getByRole('link', { name: /Studierendenparlament/ })).toHaveAttribute(
      'href',
      '/protocols/stupa',
    );
    expect(within(rows[1]).getByText('Letztes Protokoll 29.09.2026')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('8');
    expect(TestBed.inject(Meta).getTag('name="robots"')?.content).toBe('noindex');
  });

  /** Spec 002401: the same Gremien lead to the decisions. */
  it('leads to the decisions of each gremium', async () => {
    await setup('decisions');
    expect(screen.getByRole('heading', { level: 1, name: 'Beschlüsse' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /AStA/ })).toHaveAttribute('href', '/decisions/asta');
    expect(screen.queryByText(/öffentliche Fassung/)).toBeNull();
  });

  it('takes the protocols when the route names no page', async () => {
    await setup(undefined);
    expect(screen.getByRole('link', { name: /AStA/ })).toHaveAttribute('href', '/protocols/asta');
  });

  /** The Gremien answer after the render, so the router spy is in place before the redirect. */
  async function oldLink(committee: readonly string[]) {
    const answer = new Subject<PublicGremium[]>();
    await setup('decisions', makeApi({ gremien: jest.fn(() => answer) }), committee);
    const navigate = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    answer.next(GREMIEN);
    answer.complete();
    return navigate;
  }

  /** Spec 002404: an old link with one public Gremium opens its page. */
  it('opens the page of the gremium of an old filter link', async () => {
    const navigate = await oldLink(['g-1']);
    expect(navigate).toHaveBeenCalledWith(['/', 'decisions', 'stupa'], { replaceUrl: true });
  });

  it('stays on the list for an old link with several gremien', async () => {
    const navigate = await oldLink(['g-1', 'g-2']);
    expect(navigate).not.toHaveBeenCalled();
    expect(await screen.findAllByRole('listitem')).toHaveLength(2);
  });

  it('stays on the list for an old link with an unknown gremium', async () => {
    const navigate = await oldLink(['g-x']);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('says that no gremium publishes yet and links back to the start', async () => {
    await setup('protocols', makeApi({ gremien: jest.fn(() => of([])) }));
    expect(screen.getByText('Noch keine öffentlichen Protokolle')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Zur Startseite/ })).toHaveAttribute('href', '/');
  });

  it('says that no decision is public yet', async () => {
    await setup('decisions', makeApi({ gremien: jest.fn(() => of([])) }));
    expect(screen.getByText('Noch keine öffentlichen Beschlüsse')).toBeInTheDocument();
  });

  it('reports a failed read', async () => {
    await setup('protocols', makeApi({ gremien: jest.fn(() => throwError(() => new Error('down'))) }));
    expect(screen.getByRole('alert')).toHaveTextContent('Die Protokolle konnten nicht geladen werden.');
  });

  it('localizes to English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup();
    expect(screen.getAllByText(/^Latest protocol /)).toHaveLength(2);
  });
});
