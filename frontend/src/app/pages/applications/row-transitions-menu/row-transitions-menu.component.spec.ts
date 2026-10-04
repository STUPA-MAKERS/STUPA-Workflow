import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import type { ApplicationListItem, TransitionOutWire } from '@core/api/models';
import { RowTransitionsMenuComponent, type RowAction } from './row-transitions-menu.component';

const ITEM: ApplicationListItem = {
  id: 'app-1',
  typeId: 't1',
  title: 'Druck des Semesterplaners',
  state: { id: 's1', key: 'submitted', label: 'Eingereicht', color: null, editAllowed: true },
  gremiumId: null,
  amount: '480.00',
  currency: 'EUR',
  createdAt: '2026-09-24T09:30:00Z',
  updatedAt: '2026-09-24T09:30:00Z',
  archivedAt: null,
};

const TRANSITIONS: TransitionOutWire[] = [
  { id: 'tr-start', fromStateId: 's1', toStateId: 's2', label: { de: 'Prüfung beginnen' } },
  { id: 'tr-agenda', fromStateId: 's1', toStateId: 's3', label: { de: 'Auf Tagesordnung setzen' }, addsToAgenda: true },
  { id: 'tr-reject', fromStateId: 's1', toStateId: 's4', label: { de: 'Ablehnen' }, color: '#c0392b' },
  { id: 'tr-nolabel', fromStateId: 's1', toStateId: 's5', label: {} },
];

const ALL = [
  'application.transition',
  'application.share',
  'application.archive',
  'application.force_status',
  'application.delete',
];

async function setup(perms: string[] = ALL, item: ApplicationListItem = ITEM) {
  const actions: RowAction[] = [];
  const view = await render(RowTransitionsMenuComponent, {
    inputs: { item, title: item.title ?? '' },
    on: { action: (a: RowAction) => actions.push(a) },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: { can: (p: string) => perms.includes(p) } },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const trigger = screen.getByRole('button', { name: 'Aktionen für Druck des Semesterplaners' });
  return { ...view, http, actions, trigger };
}

const TRANSITIONS_URL = (r: { url: string }) => r.url === '/api/applications/app-1/transitions';

/** Let the menu render its items (it shows them after a timer). */
async function settle(detectChanges: () => void) {
  await new Promise((r) => setTimeout(r));
  detectChanges();
}

describe('RowTransitionsMenuComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the transitions only when the menu opens', async () => {
    const { http, trigger, detectChanges } = await setup();
    http.verify();
    await userEvent.click(trigger);
    expect(screen.getByRole('menu')).toHaveAttribute('aria-busy', 'true');
    http.expectOne(TRANSITIONS_URL).flush(TRANSITIONS);
    await settle(detectChanges);

    const items = screen.getAllByRole('menuitem').map((el) => el.textContent?.trim());
    expect(items).toEqual([
      'Prüfung beginnen',
      'Auf Tagesordnung setzen',
      'Ablehnen',
      'Übergang',
      'Öffnen',
      'Öffentliche Links',
      'Archivieren',
      'Status setzen',
      'Löschen',
    ]);
    // A rejection and the delete are red.
    expect(screen.getByRole('menuitem', { name: 'Ablehnen' })).toHaveClass('rm__item--danger');
    expect(screen.getByRole('menuitem', { name: 'Löschen' })).toHaveClass('rm__item--danger');
    expect(screen.getByRole('menuitem', { name: 'Öffnen' })).not.toHaveClass('rm__item--danger');
  });

  it('loads them again on every opening', async () => {
    const { http, trigger, detectChanges } = await setup();
    await userEvent.click(trigger);
    http.expectOne(TRANSITIONS_URL).flush(TRANSITIONS);
    await settle(detectChanges);
    await userEvent.keyboard('{Escape}');
    await userEvent.click(trigger);
    http.expectOne(TRANSITIONS_URL).flush([]);
    await settle(detectChanges);
    expect(screen.queryByRole('menuitem', { name: 'Prüfung beginnen' })).not.toBeInTheDocument();
  });

  it('emits the chosen transition', async () => {
    const { http, trigger, detectChanges, actions } = await setup();
    await userEvent.click(trigger);
    http.expectOne(TRANSITIONS_URL).flush(TRANSITIONS);
    await settle(detectChanges);
    await userEvent.click(screen.getByRole('menuitem', { name: 'Auf Tagesordnung setzen' }));
    expect(actions).toEqual([
      { kind: 'transition', transition: expect.objectContaining({ id: 'tr-agenda', addsToAgenda: true }) },
    ]);
  });

  it.each([
    ['Öffnen', 'open'],
    ['Öffentliche Links', 'share'],
    ['Archivieren', 'archive'],
    ['Status setzen', 'force'],
    ['Löschen', 'delete'],
  ])('emits "%s" as %s', async (label, kind) => {
    const { http, trigger, detectChanges, actions } = await setup();
    await userEvent.click(trigger);
    http.expectOne(TRANSITIONS_URL).flush([]);
    await settle(detectChanges);
    await userEvent.click(screen.getByRole('menuitem', { name: label }));
    expect(actions).toEqual([{ kind }]);
  });

  it('offers "Aus Archiv holen" for an archived row', async () => {
    const { http, trigger, detectChanges } = await setup(ALL, { ...ITEM, archivedAt: '2026-09-30T10:00:00Z' });
    await userEvent.click(trigger);
    http.expectOne(TRANSITIONS_URL).flush([]);
    await settle(detectChanges);
    expect(screen.getByRole('menuitem', { name: 'Aus Archiv holen' })).toBeInTheDocument();
  });

  it('shows only "Öffnen" without any right, and asks for no transitions', async () => {
    const { http, trigger, detectChanges } = await setup([]);
    await userEvent.click(trigger);
    await settle(detectChanges);
    http.verify();
    expect(screen.getAllByRole('menuitem').map((el) => el.textContent?.trim())).toEqual(['Öffnen']);
  });

  it('shows no transitions when they fail to load', async () => {
    const { http, trigger, detectChanges } = await setup();
    await userEvent.click(trigger);
    http.expectOne(TRANSITIONS_URL).flush({}, { status: 500, statusText: 'x' });
    await settle(detectChanges);
    expect(screen.getByRole('menuitem', { name: 'Öffnen' })).toBeInTheDocument();
    expect(screen.queryByText('Übergänge')).not.toBeInTheDocument();
  });

  it('drops a late answer of an earlier opening', async () => {
    const { http, trigger, detectChanges, fixture } = await setup();
    await userEvent.click(trigger);
    const first = http.expectOne(TRANSITIONS_URL);
    await userEvent.keyboard('{Escape}');
    await userEvent.click(trigger);
    const second = http.expectOne(TRANSITIONS_URL);
    first.flush(TRANSITIONS);
    const cmp = fixture.componentInstance as unknown as { pending: () => boolean };
    expect(cmp.pending()).toBe(true);
    second.flush({}, { status: 500, statusText: 'x' });
    await settle(detectChanges);
    expect(cmp.pending()).toBe(false);
  });

  it('ignores a late error of an earlier opening', async () => {
    const { http, trigger, fixture } = await setup();
    await userEvent.click(trigger);
    const first = http.expectOne(TRANSITIONS_URL);
    await userEvent.keyboard('{Escape}');
    await userEvent.click(trigger);
    const second = http.expectOne(TRANSITIONS_URL);
    first.flush({}, { status: 500, statusText: 'x' });
    const cmp = fixture.componentInstance as unknown as { pending: () => boolean };
    expect(cmp.pending()).toBe(true);
    second.flush([]);
    expect(cmp.pending()).toBe(false);
  });

  it('ignores an item it does not know', async () => {
    const { fixture, actions } = await setup();
    const cmp = fixture.componentInstance as unknown as { onSelected: (i: { id: string; label: string }) => void };
    cmp.onSelected({ id: 't:gone', label: 'x' });
    expect(actions).toEqual([]);
  });
});
