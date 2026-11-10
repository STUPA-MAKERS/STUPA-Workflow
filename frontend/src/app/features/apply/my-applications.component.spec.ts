import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen, waitFor } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicantApplications } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { createLocationMock, provideLocationMock } from '../../../testing/location-mock';
import { MyApplicationsComponent } from './my-applications.component';

const LIST: ApplicantApplications = {
  email: 'lena@example.org',
  items: [
    {
      id: 'a1',
      title: 'Zuschuss Erstsemesterfahrt',
      state: { id: 's1', key: 'submitted', label: { de: 'Eingereicht', en: 'Submitted' }, color: null, editAllowed: true, kind: 'normal' },
      typeId: 't1',
      amount: '480.00',
      approvedAmount: null,
      currency: 'EUR',
      createdAt: '2026-11-02T10:00:00Z',
    },
    {
      id: 'a2',
      title: 'Neue Bänke',
      state: null,
      typeId: 't2',
      amount: null,
      approvedAmount: null,
      currency: null,
      createdAt: '2026-03-12T10:00:00Z',
    },
  ],
} as unknown as ApplicantApplications;

interface Opts {
  fragment?: string | null;
  childId?: string | null;
  list?: () => ReturnType<ApiClient['applicantApplications']>;
  verify?: jest.Mock;
  typesFail?: boolean;
}

async function setup(o: Opts = {}) {
  localStorage.setItem('ap.locale', 'de');
  const navigate = jest.spyOn(Router.prototype, 'navigate').mockResolvedValue(true);
  const verify = o.verify ?? jest.fn(() => of(undefined));
  const list = jest.fn(o.list ?? (() => of(LIST)));
  const auth = { markApplicantSession: jest.fn() };
  const location = createLocationMock({
    href: 'http://localhost/my-applications#t=tok',
    pathname: '/my-applications',
    hash: '#t=tok',
  });
  const api: Partial<ApiClient> = {
    applicationTypes: (() =>
      o.typesFail ? throwError(() => new Error('x')) : of([
        { id: 't1', name: 'Finanzantrag' },
        { id: 't2', name: 'Sonstiger Antrag' },
      ])) as unknown as ApiClient['applicationTypes'],
    applicantApplications: list as unknown as ApiClient['applicantApplications'],
    verifyEmailLogin: verify as unknown as ApiClient['verifyEmailLogin'],
  };
  const child = o.childId ? { paramMap: convertToParamMap({ id: o.childId }) } : null;
  const view = await render(MyApplicationsComponent, {
    providers: [
      provideRouter([]),
      provideLocationMock(location),
      { provide: ApiClient, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: ActivatedRoute, useValue: { snapshot: { fragment: o.fragment ?? null, firstChild: child } } },
    ],
  });
  return { ...view, navigate, verify, list, auth };
}

/** F/applications/applications/000588 and F/administration/accounts/000583. */
describe('MyApplicationsComponent', () => {
  afterEach(() => {
    jest.restoreAllMocks();
    localStorage.clear();
  });

  it('lists the Anträge of the session in month groups with status, type and amount', async () => {
    const { auth } = await setup();
    expect(await screen.findByText('Zuschuss Erstsemesterfahrt')).toBeInTheDocument();
    expect(screen.getByText('November 2026')).toBeInTheDocument();
    expect(screen.getByText('März 2026')).toBeInTheDocument();
    expect(screen.getByText('Eingereicht')).toBeInTheDocument();
    expect(screen.getByText('Finanzantrag')).toBeInTheDocument();
    expect(screen.getByText('Sonstiger Antrag')).toBeInTheDocument();
    expect(auth.markApplicantSession).toHaveBeenCalled();
    expect(screen.getByRole('link', { name: /Zuschuss Erstsemesterfahrt/ })).toHaveAttribute(
      'href',
      '/my-applications/a1',
    );
  });

  it('shows no "Antrag stellen"', async () => {
    await setup();
    await screen.findByText('Zuschuss Erstsemesterfahrt');
    expect(screen.queryByText('Antrag stellen')).toBeNull();
  });

  it('filters the rows by the search text', async () => {
    const { fixture } = await setup();
    await screen.findByText('Zuschuss Erstsemesterfahrt');
    fixture.componentInstance.query.set('bänke');
    fixture.detectChanges();
    expect(screen.queryByText('Zuschuss Erstsemesterfahrt')).toBeNull();
    expect(screen.getByText('Neue Bänke')).toBeInTheDocument();
  });

  it('redeems the link of the mail, strips it and loads the list', async () => {
    const replace = jest.spyOn(history, 'replaceState');
    const { verify, list } = await setup({ fragment: 't=tok' });
    expect(verify).toHaveBeenCalledWith('tok');
    await waitFor(() => expect(list).toHaveBeenCalled());
    expect(replace.mock.calls.at(-1)?.[2]).toBe('/my-applications');
  });

  it('sends an invalid link to the login page with a hint', async () => {
    const verify = jest.fn(() => throwError(() => ({ status: 410 })));
    const { navigate, list } = await setup({ fragment: 't=tok', verify });
    expect(navigate).toHaveBeenCalledWith(['/login'], { queryParams: { link: 'invalid' }, replaceUrl: true });
    expect(list).not.toHaveBeenCalled();
  });

  it('sends a visit without a session to the login page', async () => {
    const { navigate } = await setup({ list: () => throwError(() => ({ status: 401 })) });
    expect(navigate).toHaveBeenCalledWith(['/login'], { replaceUrl: true });
  });

  it('shows a deviating approved amount, names no type without the types, and goes back to the list', async () => {
    const approved = {
      ...LIST,
      items: [{ ...LIST.items[0], approvedAmount: '400.00' }, { ...LIST.items[1], amount: '10.00', approvedAmount: '10' }],
    } as ApplicantApplications;
    const { fixture, navigate } = await setup({ list: () => of(approved) });
    await screen.findByText('Zuschuss Erstsemesterfahrt');
    const rows = fixture.componentInstance.rows();
    expect(rows[0].approved).toMatch(/400,00/);
    expect(rows[1].approved).toBeNull();
    expect(rows[1].amount).toMatch(/10,00/);
    fixture.componentInstance.onBack();
    expect(navigate).toHaveBeenCalledWith(['/my-applications']);
    fixture.componentInstance.reload();
    expect(fixture.componentInstance.searchPlaceholder()).toBe('2 Anträge durchsuchen');
  });

  it('names no type when the types cannot load', async () => {
    await setup({ typesFail: true });
    await screen.findByText('Zuschuss Erstsemesterfahrt');
    expect(screen.queryByText('Finanzantrag')).toBeNull();
  });

  it('says "1 Antrag" in the search for one Antrag', async () => {
    const { fixture } = await setup({ list: () => of({ ...LIST, items: [LIST.items[0]] } as ApplicantApplications) });
    await screen.findByText('Zuschuss Erstsemesterfahrt');
    expect(fixture.componentInstance.searchPlaceholder()).toBe('1 Antrag durchsuchen');
  });

  it('leaves an old link of one Antrag to the detail pane', async () => {
    const { verify, list } = await setup({ fragment: 't=old', childId: 'a1' });
    expect(verify).not.toHaveBeenCalled();
    expect(list).not.toHaveBeenCalled();
  });
});
