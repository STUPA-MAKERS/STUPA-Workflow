import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router, convertToParamMap, type ParamMap } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { BehaviorSubject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { USE_MOCK_API } from '@core/api/api.config';
import type { GuestMe } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { guestMe } from '../../../testing/guest-fixtures';
import { AltchaService } from '../apply/altcha.service';
import { LocaleSwitchService } from '../../layout/locale-switch.service';
import { PublicMeetingComponent, normalizeJoinCode } from './public-meeting.component';

const err = (status: number, code?: string) =>
  new HttpErrorResponse({ status, error: code ? { code } : null });

async function setup(me: GuestMe | HttpErrorResponse, head = guestMe().meeting) {
  localStorage.setItem('ap.locale', 'de');
  const params = new BehaviorSubject<ParamMap>(convertToParamMap({ code: '7kq-4mp' }));
  const api = {
    publicMeeting: jest.fn(() => of(head)),
    guestMe: jest.fn(() => (me instanceof HttpErrorResponse ? throwError(() => me) : of(me))),
    joinPublicMeeting: jest.fn(() => of(guestMe({ status: 'pending', view: null }))),
    renameGuestMe: jest.fn((_c: string, name: string) => of(guestMe({ status: 'pending', displayName: name, view: null }))),
    leavePublicMeeting: jest.fn(() => of(undefined)),
    castGuestBallot: jest.fn(() => of({ status: 'cast' })),
  };
  const auth = { login: jest.fn() };
  const router = { navigate: jest.fn() };
  const view = await render(PublicMeetingComponent, {
    providers: [
      { provide: ApiClient, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: Router, useValue: router },
      { provide: ActivatedRoute, useValue: { paramMap: params.asObservable() } },
      { provide: AltchaService, useValue: { solve: () => Promise.resolve(null) } },
      { provide: USE_MOCK_API, useValue: true },
      { provide: ToastService, useValue: { success: jest.fn(), error: jest.fn() } },
    ],
  });
  return { ...view, api, auth, router, params };
}

describe('PublicMeetingComponent', () => {
  afterEach(() => jest.useRealTimers());

  it('normalizes a typed code', () => {
    expect(normalizeJoinCode(' 7kq-4mp ')).toBe('7KQ4MP');
  });

  it('shows the join form with the meeting head and joins', async () => {
    const { api, auth } = await setup(err(401, 'guest_token_missing'));
    expect(api.publicMeeting).toHaveBeenCalledWith('7KQ4MP');
    expect(screen.getByRole('heading', { name: '7. Sitzung' })).toBeInTheDocument();
    expect(screen.getByText(/^Fachschaft Informatik · seit \d\d:\d\d$/)).toBeInTheDocument();
    expect(screen.getByText(/stimme mit ab/)).toBeInTheDocument();
    const join = screen.getByRole('button', { name: /Beitreten/ });
    expect(join).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Dein Name/), 'Jana Roth{Enter}');
    expect(api.joinPublicMeeting).toHaveBeenCalledWith('7KQ4MP', 'Jana Roth', null);
    expect(await screen.findByText('Warte auf Freigabe durch die Sitzungsleitung')).toBeInTheDocument();
    expect(auth.login).not.toHaveBeenCalled();
  });

  it('offers the login to a member and names the watch mode', async () => {
    const { auth } = await setup(err(401), { ...guestMe().meeting, guestsMode: 'watch', status: 'planned', startedAt: null });
    expect(screen.getByText(/Verfolge die Sitzung live/)).toBeInTheDocument();
    expect(screen.getByText(/Fachschaft Informatik · Di\., 06\.10\.2026, 18:15/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Mit Konto anmelden' }));
    expect(auth.login).toHaveBeenCalled();
  });

  it('reports a refused join', async () => {
    const { api } = await setup(err(401));
    api.joinPublicMeeting.mockReturnValue(throwError(() => err(400, 'altcha_failed')));
    await userEvent.type(screen.getByLabelText(/Dein Name/), 'Jana Roth');
    await userEvent.click(screen.getByRole('button', { name: /Beitreten/ }));
    expect(await screen.findByText(/Spam-Prüfung/)).toBeInTheDocument();
    api.joinPublicMeeting.mockReturnValue(throwError(() => err(429)));
    await userEvent.click(screen.getByRole('button', { name: /Beitreten/ }));
    expect(await screen.findByText(/Zu viele Anfragen/)).toBeInTheDocument();
    api.joinPublicMeeting.mockReturnValue(throwError(() => err(500)));
    await userEvent.click(screen.getByRole('button', { name: /Beitreten/ }));
    expect(await screen.findByText(/ging nicht durch/)).toBeInTheDocument();
  });

  it('lets a pending guest change the name and withdraw', async () => {
    const { api } = await setup(guestMe({ status: 'pending', view: null }));
    expect(screen.getByText(/Du hast als Jana Roth angefragt/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Name ändern/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    await userEvent.click(screen.getByRole('button', { name: /Name ändern/ }));
    const input = screen.getByLabelText(/Dein Name/);
    await userEvent.clear(input);
    await userEvent.type(input, 'Jana R.{Enter}');
    expect(api.renameGuestMe).toHaveBeenCalledWith('7KQ4MP', 'Jana R.');
    await userEvent.click(screen.getByRole('button', { name: 'Anfrage zurückziehen' }));
    expect(api.leavePublicMeeting).toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: /Beitreten/ })).toBeInTheDocument();
  });

  it('offers the menu actions of the header', async () => {
    const { api, fixture } = await setup(guestMe({ status: 'pending', view: null }));
    const cmp = fixture.componentInstance;
    cmp.onMenu('rename');
    fixture.detectChanges();
    expect(screen.getByLabelText(/Dein Name/)).toBeInTheDocument();
    cmp.onMenu('other');
    cmp.onMenu('leave');
    expect(api.leavePublicMeeting).toHaveBeenCalled();
  });

  it('counts down the new request of a rejected guest', async () => {
    jest.useFakeTimers({ now: new Date('2026-10-06T16:52:00Z') });
    const { api, fixture } = await setup(guestMe({ status: 'rejected', retryAfter: 120, view: null }));
    expect(screen.getByText('Anfrage abgelehnt')).toBeInTheDocument();
    expect(screen.getByText(/Wieder möglich ab \d\d:\d\d \(2 Minuten\)/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Erneut anfragen/ })).toBeDisabled();
    jest.advanceTimersByTime(121_000);
    fixture.detectChanges();
    const retry = screen.getByRole('button', { name: /Erneut anfragen/ });
    expect(retry).toBeEnabled();
    retry.click();
    await Promise.resolve();
    expect(api.joinPublicMeeting).toHaveBeenCalledWith('7KQ4MP', 'Jana Roth', null);
  });

  it('tells a removed guest and the other final states', async () => {
    await setup(guestMe({ status: 'removed', retryAfter: null, view: null }));
    expect(screen.getByText('Du bist nicht mehr in der Sitzung')).toBeInTheDocument();
  });

  it('shows a closed meeting', async () => {
    await setup(err(401), { ...guestMe().meeting, status: 'closed' });
    expect(screen.getByText('Die Sitzung ist beendet')).toBeInTheDocument();
  });

  it('shows a meeting that is no longer public, with the login', async () => {
    const { api } = await setup(err(404, 'meeting_not_public'));
    expect(api.guestMe).toHaveBeenCalled();
    expect(screen.getByText('Die Sitzung ist nicht mehr öffentlich')).toBeInTheDocument();
  });

  it('lets an unknown code be typed again', async () => {
    localStorage.setItem('ap.locale', 'de');
    const { api, router, fixture } = await setup(err(401));
    api.publicMeeting.mockReturnValue(throwError(() => err(404, 'join_code_unknown')));
    fixture.componentInstance['guest'].load('XXX');
    fixture.detectChanges();
    expect(screen.getByText('Dieser Link ist ungültig oder die Sitzung ist beendet.')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Code der Sitzung'), 'abc');
    await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));
    expect(router.navigate).not.toHaveBeenCalled();
    await userEvent.clear(screen.getByLabelText('Code der Sitzung'));
    await userEvent.type(screen.getByLabelText('Code der Sitzung'), '9xh-2tr');
    await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));
    expect(router.navigate).toHaveBeenCalledWith(['/j', '9XH2TR']);
  });

  it('shows the not-public and the error state with a reload', async () => {
    const { api, fixture } = await setup(err(401));
    api.publicMeeting.mockReturnValue(throwError(() => err(404, 'meeting_not_public')));
    fixture.componentInstance['guest'].load('7KQ4MP');
    fixture.detectChanges();
    expect(screen.getByText('Die Sitzung ist nicht mehr öffentlich')).toBeInTheDocument();
    api.publicMeeting.mockReturnValue(throwError(() => err(500)));
    fixture.componentInstance['guest'].load('7KQ4MP');
    fixture.detectChanges();
    expect(screen.getByText('Die Sitzung lädt gerade nicht')).toBeInTheDocument();
    api.publicMeeting.mockReturnValue(of(guestMe().meeting));
    await userEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(api.publicMeeting).toHaveBeenCalledTimes(4);
  });

  it('shows the participant view after the admission and leaves the meeting', async () => {
    const { api } = await setup(guestMe({ view: { ...guestMe().view!, votes: [] } }));
    expect(screen.getByText('Du bist zugelassen')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sitzung verlassen' }));
    expect(api.leavePublicMeeting).toHaveBeenCalledWith('7KQ4MP');
  });

  it('names a pseudonymized guest "Gast n"', async () => {
    await setup(guestMe({ displayName: null, number: 5 }));
    expect(screen.getByText('Gast 5')).toBeInTheDocument();
  });

  it('keeps its derived texts empty while nothing is loaded, and guards its actions', async () => {
    localStorage.setItem('ap.locale', 'de');
    const api = {
      publicMeeting: jest.fn(() => ({ subscribe: () => {} })),
      guestMe: jest.fn(),
      joinPublicMeeting: jest.fn(),
      renameGuestMe: jest.fn(),
    };
    const { fixture } = await render(PublicMeetingComponent, {
      providers: [
        { provide: ApiClient, useValue: api },
        { provide: AuthService, useValue: { login: jest.fn() } },
        { provide: Router, useValue: { navigate: jest.fn() } },
        { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({})) } },
        { provide: AltchaService, useValue: { solve: () => Promise.resolve(null) } },
        { provide: USE_MOCK_API, useValue: true },
      ],
    });
    const cmp = fixture.componentInstance;
    expect(api.publicMeeting).toHaveBeenCalledWith('');
    expect(cmp['status']()).toBeNull();
    expect(cmp['metaLine']()).toBe('');
    expect(cmp['ownName']()).toBe('');
    expect(cmp['retryLine']()).toBe('');
    expect(cmp['menu']()).toEqual([]);
    cmp.join();
    cmp.saveRename();
    expect(api.joinPublicMeeting).not.toHaveBeenCalled();
    expect(api.renameGuestMe).not.toHaveBeenCalled();
    cmp.retry();
    expect(cmp['dateText']('kaputt', null)).toBe('kaputt');
  });

  it('shows a planned meeting without a Gremium by its date only', async () => {
    const { fixture } = await setup(err(401), {
      ...guestMe().meeting,
      gremiumName: null,
      status: 'planned',
      startedAt: null,
      startTime: null,
    });
    expect(fixture.componentInstance['metaLine']()).toMatch(/^Di\., 06\.10\.2026$/);
    fixture.componentInstance['startTicker']();
    fixture.componentInstance['startTicker']();
    fixture.destroy();
  });

  it('shows a head without a date and asks again with the typed name', async () => {
    const noDate = { ...guestMe().meeting, status: 'planned' as const, startedAt: null, date: null };
    const { fixture, api } = await setup(
      guestMe({ status: 'rejected', displayName: null, retryAfter: 0, view: null, meeting: noDate }),
      noDate,
    );
    const cmp = fixture.componentInstance;
    expect(cmp['metaLine']()).toBe('Fachschaft Informatik');
    expect(cmp['menu']()).toEqual([]);
    cmp['name'].set('Neuer Name');
    cmp.retry();
    await Promise.resolve();
    expect(api.joinPublicMeeting).toHaveBeenCalledWith('7KQ4MP', 'Neuer Name', null);
  });

  it('has its own bar with the wordmark and the language switch, and the footer', async () => {
    const switchTo = jest.spyOn(LocaleSwitchService.prototype, 'switchTo').mockImplementation(() => {});
    const { container } = await setup(err(401));
    expect(container.querySelector('.pm__logo')).not.toBeNull();
    expect(container.querySelector('app-site-footer')).not.toBeNull();
    // D8: the app list, never a native select.
    expect(container.querySelector('select')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Sprache wechseln: DE' }));
    await userEvent.click(screen.getByRole('option', { name: 'English' }));
    expect(switchTo).toHaveBeenCalledWith('en');
    switchTo.mockRestore();
  });
});
