import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { LINK } from '../../../../testing/guest-fixtures';
import { matchMediaQueries, meeting } from '../../../../testing/meeting-fixtures';
import { MeetingGuestsService } from '../meeting-guests.service';
import { JOIN_COPIED_MS, JoinLinkComponent } from './join-link.component';
import { JoinQrComponent } from './join-qr.component';
import { PublicJoinSettingsComponent } from './public-join-settings.component';

let restore: (() => void) | null = null;
beforeEach(() => localStorage.setItem('ap.locale', 'de'));
afterEach(() => {
  restore?.();
  restore = null;
  jest.useRealTimers();
  document.body.style.overflow = '';
});

function clipboard(ok = true) {
  const writeText = jest.fn(() => (ok ? Promise.resolve() : Promise.reject(new Error('denied'))));
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  return writeText;
}

describe('JoinLinkComponent', () => {
  it('shows the code and the full URL, copies it and asks before a new link', async () => {
    const writeText = clipboard();
    const rotate = jest.fn();
    const { fixture } = await render(JoinLinkComponent, { inputs: { link: LINK }, on: { rotate } });
    expect(screen.getByText('Beitrittslink · Code 7KQ-4MP')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: LINK.joinUrl })).toHaveAttribute('rel', 'noopener');
    jest.useFakeTimers();
    screen.getByRole('button', { name: /Kopieren/ }).click();
    await Promise.resolve();
    await Promise.resolve();
    fixture.detectChanges();
    expect(writeText).toHaveBeenCalledWith(LINK.joinUrl);
    expect(screen.getByRole('button', { name: /Kopiert/ })).toBeInTheDocument();
    // A second copy restarts the timer.
    screen.getByRole('button', { name: /Kopiert/ }).click();
    await Promise.resolve();
    await Promise.resolve();
    jest.advanceTimersByTime(JOIN_COPIED_MS);
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: /Kopieren/ })).toBeInTheDocument();
    jest.useRealTimers();

    await userEvent.click(screen.getByRole('button', { name: /Neuen Link erzeugen/ }));
    expect(screen.getByRole('alert')).toHaveTextContent('gelten dann nicht mehr');
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(rotate).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: /Neuen Link erzeugen/ }));
    await userEvent.click(screen.getAllByRole('button', { name: /Neuen Link erzeugen/ })[0]);
    expect(rotate).toHaveBeenCalled();
  });

  it('keeps the label when the clipboard refuses, and offers "Groß zeigen" in the sheet', async () => {
    clipboard(false);
    const showLarge = jest.fn();
    const { fixture } = await render(JoinLinkComponent, {
      inputs: { link: LINK, canRotate: false },
      on: { showLarge },
    });
    screen.getByRole('button', { name: /Kopieren/ }).click();
    await Promise.resolve();
    await Promise.resolve();
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: /Kopieren/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Neuen Link/ })).toBeNull();
    fixture.componentRef.setInput('variant', 'sheet');
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: /Groß zeigen/ }));
    expect(showLarge).toHaveBeenCalled();
    fixture.destroy();
  });
});

describe('PublicJoinSettingsComponent', () => {
  it('turns the participation on and picks the guest mode', async () => {
    const { fixture } = await render(PublicJoinSettingsComponent, { inputs: { creating: true } });
    const cmp = fixture.componentInstance;
    expect(screen.queryByText('Gäste in dieser Sitzung')).toBeNull();
    await userEvent.click(screen.getByRole('switch', { name: /Öffentliche Teilnahme/ }));
    expect(cmp.publicJoin()).toBe(true);
    expect(screen.getByText(/Link und QR-Code gibt es nach dem Anlegen/)).toBeInTheDocument();
    expect(screen.getByText(/Einzelne Abstimmungen/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: /Gäste schauen nur zu/ }));
    expect(cmp.guestsMode()).toBe('watch');
    expect(screen.queryByText(/Einzelne Abstimmungen/)).toBeNull();
    cmp.setMode('other');
    expect(cmp.guestsMode()).toBe('watch');
  });

  it('shows the link of an existing meeting and passes the rotation on', async () => {
    const rotate = jest.fn();
    await render(PublicJoinSettingsComponent, {
      inputs: { publicJoin: true, link: LINK },
      on: { rotate },
    });
    expect(screen.getByText(LINK.joinUrl)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Neuen Link erzeugen/ }));
    await userEvent.click(screen.getAllByRole('button', { name: /Neuen Link erzeugen/ })[0]);
    expect(rotate).toHaveBeenCalled();
  });
});

describe('JoinQrComponent', () => {
  async function setup(media: string[] = [], over = {}) {
    restore = matchMediaQueries(...media);
    const api = { listMeetingGuests: jest.fn(() => of([])), getJoinLink: jest.fn(() => of(LINK)) };
    const m = meeting({ publicJoin: true, joinCode: '7KQ4MP', ...over });
    const beamer = jest.fn();
    const view = await render(JoinQrComponent, {
      inputs: { meeting: m },
      on: { beamer },
      providers: [
        MeetingGuestsService,
        { provide: ApiClient, useValue: api },
        { provide: ToastService, useValue: {} },
      ],
    });
    view.fixture.debugElement.injector.get(MeetingGuestsService).sync(m);
    view.fixture.detectChanges();
    return { ...view, beamer };
  }

  it('opens a popover with the large code, copies the link and shows it on the beamer', async () => {
    const writeText = clipboard();
    const { beamer, fixture } = await setup();
    await userEvent.click(screen.getByRole('button', { name: /QR-Code/ }));
    const pop = screen.getByRole('dialog', { name: 'QR-Code zum Beitreten' });
    expect(pop).toHaveTextContent('Mit dem Handy scannen');
    expect(pop).toHaveTextContent('Code 7KQ-4MP');
    jest.useFakeTimers();
    screen.getByRole('button', { name: /Link kopieren/ }).click();
    await Promise.resolve();
    await Promise.resolve();
    fixture.detectChanges();
    expect(writeText).toHaveBeenCalledWith(LINK.joinUrl);
    screen.getByRole('button', { name: /Kopiert/ }).click();
    await Promise.resolve();
    await Promise.resolve();
    jest.advanceTimersByTime(JOIN_COPIED_MS);
    jest.useRealTimers();
    await userEvent.click(screen.getByRole('button', { name: /Auf dem Beamer zeigen/ }));
    expect(beamer).toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: 'QR-Code zum Beitreten' })).toBeNull();
    fixture.destroy();
  });

  it('closes on the backdrop and on Escape, and does nothing without a link', async () => {
    clipboard(false);
    const { container, fixture } = await setup();
    await userEvent.click(screen.getByRole('button', { name: /QR-Code/ }));
    (container.querySelector('.jq__backdrop') as HTMLElement).click();
    fixture.detectChanges();
    expect(screen.queryByRole('dialog', { name: 'QR-Code zum Beitreten' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /QR-Code/ }));
    screen.getByRole('button', { name: /Link kopieren/ }).click();
    await Promise.resolve();
    await Promise.resolve();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'QR-Code zum Beitreten' })).toBeNull();
    const cmp = fixture.componentInstance;
    fixture.componentRef.setInput('meeting', meeting({ publicJoin: false }));
    fixture.detectChanges();
    cmp.copy();
    expect(screen.queryByRole('button', { name: /QR-Code/ })).toBeNull();
  });

  it('opens as a bottom sheet on a phone, without the beamer action', async () => {
    const { fixture } = await setup([MEDIA.phone]);
    fixture.componentRef.setInput('button', false);
    fixture.componentInstance.open.set(true);
    fixture.detectChanges();
    expect(await screen.findByText('Mit dem Handy scannen')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Auf dem Beamer zeigen/ })).toBeNull();
  });

describe('public participation needs a gremium without a quorum', () => {
  it('locks the switch and names the quorum, but lets a public meeting switch off', async () => {
    const { fixture } = await render(PublicJoinSettingsComponent, { inputs: { allowed: false, quorumPercent: 50 } });
    expect(screen.getByRole('switch', { name: /Öffentliche Teilnahme/ })).toBeDisabled();
    expect(screen.getByText('Nur in Gremien ohne Quorum möglich. Dieses Gremium hat ein Quorum von 50 %.')).toBeInTheDocument();
    fixture.componentRef.setInput('quorumPercent', null);
    fixture.componentInstance.publicJoin.set(true);
    fixture.detectChanges();
    expect(screen.getByText('Nur in Gremien ohne Quorum möglich.')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: /Öffentliche Teilnahme/ })).toBeEnabled();
  });
});
});
