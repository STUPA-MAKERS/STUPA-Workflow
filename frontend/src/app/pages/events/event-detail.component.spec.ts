import { provideTestStatuses } from '@core/api/statuses.service';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { BehaviorSubject, Subject, of, throwError } from 'rxjs';
import { type EventDetail, EventsApiService } from '@core/api/events.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { eventDetail } from '../../../testing/event-fixtures';
import { NO_LINKED_TODOS } from '../../../testing/todo-fixtures';
import { EventDetailComponent } from './event-detail.component';
import { EventsRefresh } from './events-refresh';

const FULL = eventDetail({
  decisions: [
    {
      kind: 'decision',
      targetId: 'a-1',
      title: 'Antrag Erstiparty',
      decidedAt: '2026-11-01T18:00:00Z',
      meetingTitle: 'StuPa 3',
      result: 'passed',
      amount: '400.00',
      conditions: ['Belege bis Dezember'],
    },
    { kind: 'vote', targetId: 'v-1', title: 'Umfrage', decidedAt: null, meetingTitle: null, result: null, amount: null, conditions: [] },
    { kind: 'vote', targetId: null, title: 'Ohne Ziel', decidedAt: null, meetingTitle: null, result: null, amount: null, conditions: [] },
  ],
  editions: [
    {
      id: 'e-0',
      number: 'V-AAAAAAAA',
      title: 'Erstiparty 2025',
      status: 'settled',
      startsOn: '2025-11-20',
      endsOn: null,
      startTime: null,
      endTime: null,
      totals: { requested: '0', approved: '0', expenses: '0', income: '0', balance: '-20.00' },
    },
  ],
  hiddenEditions: 2,
});

async function setup(first: EventDetail = FULL) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    get: jest.fn(() => of(first)),
    setStatus: jest.fn((_id: string, status: string) => of({ ...first, status, version: 2 })),
    remove: jest.fn(() => of(undefined)),
  };
  const paramMap = new BehaviorSubject(convertToParamMap({ id: first.id }));
  const view = await render(EventDetailComponent, {
    providers: [
      provideTestStatuses(),
      provideRouter([]),
      NO_LINKED_TODOS,
      { provide: EventsApiService, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: { paramMap, snapshot: { queryParamMap: convertToParamMap({}), fragment: null }, queryParamMap: of(convertToParamMap({})), fragment: of(null) },
      },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  const injector = view.fixture.debugElement.injector;
  const toast = jest.spyOn(injector.get(ToastService), 'show');
  const navigate = jest.spyOn(injector.get(Router), 'navigate').mockResolvedValue(true);
  const touched = jest.fn();
  injector.get(EventsRefresh).changed.subscribe(touched);
  const keys = (): string[] => cmp.actions().map((a: { key: string }) => a.key);
  return { ...view, cmp, api, paramMap, toast, navigate, touched, keys };
}

describe('EventDetailComponent', () => {
  afterEach(() => localStorage.clear());

  /** §F/collaboration/events/003029: the sections in their order. */
  it('shows the head, the fields, the money, the decisions, the series and "Verknüpft" in this order', async () => {
    const { cmp, api, container } = await setup();
    expect(api.get).toHaveBeenCalledWith('e-1');
    expect(cmp.head()).toEqual({ title: 'Erstiparty', kicker: 'V-7K3QX9MD', back: null });
    expect(screen.getByRole('heading', { name: 'Erstiparty', level: 1 })).toBeInTheDocument();
    const order = Array.from(container.querySelectorAll('[data-testid="ed-status"], [data-testid="ed-section"]')).map((el) =>
      el.getAttribute('data-testid') === 'ed-status' ? 'status' : (el.querySelector('h2, h3, h4')?.textContent?.trim() ?? el.tagName.toLowerCase()),
    );
    expect(order).toEqual(['status', 'Angaben', 'Finanzen', 'Beschlüsse', 'Weitere Veranstaltungen der Reihe', 'app-todo-linked-list']);
    expect(cmp.facts().map((f: { label: string }) => f.label)).toEqual(['Team', 'Beginn', 'Ort', 'Teilnehmende', 'Reihe', 'Shop']);
    expect(screen.getAllByTestId('ed-total')).toHaveLength(5);
    expect(cmp.totals()[4].value).toMatch(/^\+312,00\s€$/);
    expect(screen.getByTestId('ed-description')).toHaveTextContent('Party im');
  });

  /** §F/collaboration/events/003132: "Beginn" and "Ende" as two fields in one row. */
  it('shows the start and the end side by side', async () => {
    const { cmp } = await setup();
    const pair = screen.getByTestId('ed-pair');
    const rows = Array.from(pair.querySelectorAll('[data-testid="ed-fact"]')).map((r) => r.textContent?.replace(/\s+/g, ' ').trim());
    expect(rows).toEqual(['Beginn 20.11.2026, 19:00', 'Ende 21.11.2026, 02:00']);
    expect(screen.getAllByTestId('ed-pair')).toHaveLength(1);
    const day = (patch: Partial<EventDetail>) => cmp.dates({ ...FULL, ...patch }, 'de-DE');
    expect(day({ endsOn: null, endTime: '22:00:00' })).toEqual({
      label: 'Beginn',
      value: '20.11.2026, 19:00',
      beside: { label: 'Ende', value: '20.11.2026, 22:00' },
    });
    expect(day({ startTime: null, endsOn: null, endTime: null })).toEqual({ label: 'Beginn', value: '20.11.2026' });
    expect(day({ startsOn: null })).toBeNull();
  });

  /** §F/collaboration/events/003024: the shop opens in a new tab. */
  it('shows the shop as a link that opens a new tab', async () => {
    await setup();
    const link = screen.getByTestId('ed-shop');
    expect(link).toHaveAttribute('href', 'https://shop.example.org/erstiparty');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  /** §F/collaboration/todos/000482 and 000483: the decisions and the other editions. */
  it('writes the decisions and the other Events of the series', async () => {
    const { cmp } = await setup();
    const [decision, vote, bare] = FULL.decisions;
    expect(cmp.decisionLink(decision)).toEqual(['/applications', 'a-1']);
    expect(cmp.decisionLink(vote)).toEqual(['/voting', 'v-1']);
    expect(cmp.decisionLink(bare)).toBeNull();
    expect(cmp.decisionTitle(decision)).toBe('Antrag Erstiparty: Angenommen');
    expect(cmp.decisionTitle({ ...decision, result: 'unknown' })).toBe('Antrag Erstiparty');
    expect(cmp.decisionTitle(vote)).toBe('Umfrage');
    expect(cmp.decisionSub(decision)).toMatch(/^StuPa 3 · 01\.11\.2026 · 400,00\s€ · Auflage: Belege bis Dezember$/);
    expect(cmp.decisionSub(vote)).toBe('');
    expect(cmp.editionSub(FULL.editions[0])).toMatch(/^20\.11\.2025 · Abgerechnet · Saldo −?-?20,00\s€$/);
    expect(screen.getAllByTestId('ed-decision')).toHaveLength(3);
    expect(screen.getAllByTestId('ed-edition')).toHaveLength(1);
    expect(screen.getByTestId('ed-hidden')).toHaveTextContent('2 weitere ohne Zugriff');
  });

  it('leaves out the empty fields, decisions and editions', async () => {
    const bare = eventDetail({
      teamName: null,
      startsOn: null,
      endsOn: null,
      startTime: null,
      endTime: null,
      place: null,
      participants: null,
      seriesName: null,
      shopUrl: null,
      descriptionMd: null,
      hiddenEditions: 1,
    });
    const { cmp } = await setup(bare);
    expect(cmp.facts()).toEqual([]);
    expect(screen.queryByTestId('ed-decision')).toBeNull();
    expect(screen.queryByTestId('ed-edition')).toBeNull();
    expect(screen.getByTestId('ed-hidden')).toBeInTheDocument();
  });

  /** §F/collaboration/events/003042 and 003030: the field "Status", the menu and the follow-up. */
  it('offers every status in the field "Status" and keeps the menu free of statuses', async () => {
    const { cmp, keys } = await setup();
    expect(cmp.statusOptions()).toEqual([
      { value: 'planned', label: 'Geplant' },
      { value: 'settled', label: 'Abgerechnet' },
      { value: 'cancelled', label: 'Abgesagt' },
    ]);
    expect(cmp.statusPick()).toBe('planned');
    expect(screen.getByTestId('ed-status')).toBeInTheDocument();
    expect(keys()).toEqual(['edit', 'followUp', 'delete']);
    const follow = cmp.actions().find((a: { key: string }) => a.key === 'followUp');
    expect(follow.route).toEqual({ commands: ['/events', 'new'], query: { from: 'e-1' } });
  });

  it('sets a status and tells the list', async () => {
    const { cmp, api, touched } = await setup();
    cmp.setStatus('planned');
    expect(api.setStatus).not.toHaveBeenCalled();
    cmp.setStatus('cancelled');
    expect(api.setStatus).toHaveBeenCalledWith('e-1', 'cancelled', 1);
    expect(cmp.event().status).toBe('cancelled');
    expect(cmp.statusPick()).toBe('cancelled');
    expect(touched).toHaveBeenCalled();
    cmp.onAction('edit');
  });

  it('reads the Event again after a conflict and says when a status fails', async () => {
    const { cmp, api, toast } = await setup();
    api.setStatus.mockReturnValueOnce(throwError(() => ({ error: { code: 'event_version_conflict' } })));
    cmp.setStatus('settled');
    expect(toast).toHaveBeenCalledWith('Die Veranstaltung wurde inzwischen geändert. Sie ist neu geladen.', 'error');
    expect(api.get).toHaveBeenCalledTimes(2);
    api.setStatus.mockReturnValueOnce(throwError(() => ({ error: null })));
    cmp.statusPick.set('settled');
    cmp.setStatus('settled');
    expect(toast).toHaveBeenLastCalledWith('Die Veranstaltung konnte nicht gespeichert werden.', 'error');
    expect(cmp.statusPick()).toBe('planned');
  });

  /** The decision "Dialog beim Löschen": the delete asks first. */
  it('deletes the Event after the confirm and goes back to the list', async () => {
    const { cmp, api, navigate, touched, toast } = await setup();
    cmp.onAction('delete');
    expect(cmp.deleting()).toBe(true);
    cmp.confirmDelete();
    expect(api.remove).toHaveBeenCalledWith('e-1');
    expect(touched).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(['/events'], { queryParamsHandling: 'preserve' });
    api.remove.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.confirmDelete();
    expect(toast).toHaveBeenCalledWith('Die Veranstaltung konnte nicht gelöscht werden.', 'error');
    expect(cmp.deleting()).toBe(false);
  });

  it('shows the error with a retry and nothing to do without an Event', async () => {
    const { cmp, api } = await setup();
    api.get.mockReturnValueOnce(throwError(() => ({ status: 404 })));
    cmp.event.set(null);
    (cmp as { load: () => void }).load();
    const failed = cmp.state();
    expect(failed).toMatchObject({ state: 'error', message: 'Die Veranstaltung konnte nicht geladen werden.' });
    expect(cmp.head()).toEqual({ title: 'Veranstaltungen', back: null });
    expect(cmp.actions()).toEqual([]);
    expect(cmp.facts()).toEqual([]);
    expect(cmp.totals()).toEqual([]);
    cmp.setStatus('settled');
    cmp.confirmDelete();
    expect(api.setStatus).not.toHaveBeenCalled();
    expect(api.remove).not.toHaveBeenCalled();
    failed.retry();
    expect(cmp.state().state).toBe('ready');
  });

  it('drops the answer of an Event that the pane left', async () => {
    const { cmp, api, paramMap } = await setup();
    const late = new Subject<EventDetail>();
    const lateFail = new Subject<EventDetail>();
    api.get.mockReturnValueOnce(late as never).mockReturnValueOnce(lateFail as never).mockReturnValueOnce(new Subject() as never);
    paramMap.next(convertToParamMap({ id: 'e-2' }));
    paramMap.next(convertToParamMap({ id: 'e-3' }));
    paramMap.next(convertToParamMap({ id: 'e-4' }));
    late.next(eventDetail({ id: 'e-2' }));
    lateFail.error({ status: 404 });
    expect(cmp.event()).toBeNull();
    expect(cmp.state()).toEqual({ state: 'loading' });
  });
});
