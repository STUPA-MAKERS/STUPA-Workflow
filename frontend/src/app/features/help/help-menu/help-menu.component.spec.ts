import { signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { DisplaySettingsService, MEDIA, ThemeService } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { HelpService } from '../help.service';
import { HelpMenuComponent, type HelpMenuKind, type HelpMenuVariant } from './help-menu.component';

const WIKI = 'https://wiki.example.org/books/stupa';

async function setup(
  opts: { variant?: HelpMenuVariant; menu?: HelpMenuKind; signedIn?: boolean; publicTickets?: boolean } = {},
) {
  localStorage.setItem('ap.locale', 'de');
  const navigated = jest.fn();
  const view = await render(HelpMenuComponent, {
    inputs: { variant: opts.variant ?? 'rail', menu: opts.menu ?? 'help' },
    on: { navigated },
    providers: [
      provideRouter([{ path: 'accessibility', children: [] }]),
      { provide: AuthService, useValue: { isAuthenticated: signal(opts.signedIn ?? true) } },
      {
        provide: BrandingService,
        useValue: { wikiUrl: signal(WIKI), ticketsPublic: signal(opts.publicTickets ?? false) },
      },
    ],
  });
  const help = view.fixture.debugElement.injector.get(HelpService);
  return { ...view, navigated, help };
}

const trigger = () => screen.getByRole('button', { name: 'Hilfe' });
const panel = () => screen.queryByRole('region', { name: 'Hilfe' });

describe('HelpMenuComponent', () => {
  afterEach(() => {
    localStorage.clear();
    jest.useRealTimers();
  });

  /** The second line shows the address without the scheme. */
  it('opens beside the rail with the handbook link and the report entry', async () => {
    const { fixture, container } = await setup();
    const nav = document.createElement('nav');
    nav.getBoundingClientRect = () => ({ right: 96 }) as DOMRect;
    container.parentElement!.appendChild(nav);
    nav.appendChild(container);
    trigger().getBoundingClientRect = () => ({ right: 80, bottom: 700 }) as DOMRect;

    jest.useFakeTimers();
    trigger().click();
    fixture.detectChanges();
    jest.runAllTimers();
    expect(trigger()).toHaveAttribute('aria-expanded', 'true');
    const region = panel()!;
    expect(region.style.left).toBe('104px');
    expect(region.style.bottom).toBe(`${Math.max(8, window.innerHeight - 700)}px`);
    const wiki = screen.getByRole('link', { name: /Handbuch im Wiki/ });
    expect(wiki).toHaveAttribute('href', WIKI);
    expect(wiki).toHaveAttribute('target', '_blank');
    expect(wiki).toHaveAttribute('rel', 'noopener');
    expect(wiki).toHaveTextContent('wiki.example.org/books/stupa');
    expect(document.activeElement).toBe(wiki);
    expect(screen.getByRole('button', { name: 'Problem melden' })).toBeInTheDocument();
  });

  it('opens below the header button, aligned right', async () => {
    const { fixture } = await setup({ variant: 'header' });
    trigger().getBoundingClientRect = () => ({ right: window.innerWidth - 20, bottom: 60 }) as DOMRect;
    trigger().click();
    fixture.detectChanges();
    expect(panel()!.style.top).toBe('68px');
    expect(panel()!.style.right).toBe('20px');
  });

  it('falls back to the trigger edge outside a navigation', async () => {
    const { fixture } = await setup();
    trigger().getBoundingClientRect = () => ({ right: 50, bottom: 10000 }) as DOMRect;
    trigger().click();
    fixture.detectChanges();
    expect(panel()!.style.left).toBe('58px');
    expect(panel()!.style.bottom).toBe('8px');
  });

  it('opens the report dialog and closes', async () => {
    const { fixture, help, navigated } = await setup();
    trigger().click();
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Problem melden' }));
    fixture.detectChanges();
    expect(help.reportOpen()).toBe(true);
    expect(navigated).toHaveBeenCalled();
    expect(panel()).toBeNull();
  });

  /** The dialog stores this element and focuses it again on close. */
  it('puts the focus on the trigger before the report dialog opens, so it returns there', async () => {
    const { fixture, help } = await setup();
    let focused: Element | null = null;
    const open = help.openReport.bind(help);
    jest.spyOn(help, 'openReport').mockImplementation(() => {
      focused = document.activeElement;
      open();
    });
    trigger().click();
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Problem melden' }));
    fixture.detectChanges();
    expect(focused).toBe(trigger());
    expect(help.reportOpen()).toBe(true);
  });

  it('closes when the handbook link is followed', async () => {
    const { fixture, navigated } = await setup();
    trigger().click();
    fixture.detectChanges();
    const wiki = screen.getByRole('link', { name: /Handbuch im Wiki/ });
    wiki.addEventListener('click', (e) => e.preventDefault());
    wiki.click();
    fixture.detectChanges();
    expect(navigated).toHaveBeenCalled();
    expect(panel()).toBeNull();
  });

  /** Spec 000647: "Hilfe" holds only the handbook and the report. */
  it('keeps the display settings and the statement out of the help menu', async () => {
    await setup({ variant: 'sheet' });
    expect(screen.queryByRole('group', { name: 'Darstellung' })).toBeNull();
    expect(screen.queryByRole('switch')).toBeNull();
    expect(document.querySelector('a[href="/accessibility"]')).toBeNull();
  });

  /** Spec 000647: "Barrierefreiheit" is its own menu with the eye icon. */
  it('opens the accessibility menu from its own trigger with the eye icon', async () => {
    const { fixture } = await setup({ menu: 'a11y' });
    const button = screen.getByRole('button', { name: 'Barrierefreiheit' });
    expect(fixture.componentInstance.icon()).toBe('eye');
    button.click();
    fixture.detectChanges();
    const region = screen.getByRole('region', { name: 'Barrierefreiheit' });
    expect(region).toHaveTextContent('Darstellung');
    expect(screen.queryByRole('link', { name: /Handbuch im Wiki/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Problem melden' })).toBeNull();
  });

  /** Spec 000496: the statement is one entry away on every page, with and without a login. */
  it('links to the accessibility statement and closes when it is followed', async () => {
    const { fixture, navigated } = await setup({ menu: 'a11y', signedIn: false });
    screen.getByRole('button', { name: 'Barrierefreiheit' }).click();
    fixture.detectChanges();
    const link = screen.getByRole('link', { name: 'Erklärung zur Barrierefreiheit' });
    expect(link).toHaveAttribute('href', '/accessibility');
    link.click();
    fixture.detectChanges();
    expect(navigated).toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: 'Barrierefreiheit' })).toBeNull();
  });

  /** Escape on a closed menu does nothing. */
  it('toggles, and closes on Escape with the focus back on the trigger', async () => {
    const { fixture } = await setup();
    trigger().click();
    fixture.detectChanges();
    trigger().click();
    fixture.detectChanges();
    expect(panel()).toBeNull();

    trigger().click();
    fixture.detectChanges();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect(panel()).toBeNull();
    expect(document.activeElement).toBe(trigger());
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  });

  it('closes on a press or a focus outside and on a resize, not on one inside', async () => {
    const { fixture } = await setup();
    const outside = document.createElement('button');
    document.body.appendChild(outside);

    outside.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    outside.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));

    trigger().click();
    fixture.detectChanges();
    panel()!.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    panel()!.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
    fixture.detectChanges();
    expect(panel()).not.toBeNull();
    outside.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    fixture.detectChanges();
    expect(panel()).toBeNull();

    trigger().click();
    fixture.detectChanges();
    outside.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
    fixture.detectChanges();
    expect(panel()).toBeNull();

    trigger().click();
    fixture.detectChanges();
    window.dispatchEvent(new Event('resize'));
    fixture.detectChanges();
    expect(panel()).toBeNull();
    outside.remove();
  });

  it('lists the entries inline in the sheet', async () => {
    const { navigated } = await setup({ variant: 'sheet' });
    expect(screen.getByRole('group', { name: 'Hilfe' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Hilfe' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Problem melden' }));
    expect(navigated).toHaveBeenCalled();
  });

  it('hides "Problem melden" from a visitor while public tickets are off', async () => {
    await setup({ variant: 'sheet', signedIn: false });
    expect(screen.getByRole('link', { name: /Handbuch im Wiki/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Problem melden' })).not.toBeInTheDocument();
  });

  it('offers "Problem melden" to a visitor while public tickets are on', async () => {
    await setup({ variant: 'sheet', signedIn: false, publicTickets: true });
    expect(screen.getByRole('button', { name: 'Problem melden' })).toBeInTheDocument();
  });

  /** On a phone the header button opens the bottom sheet, which a popover beside it would not fit. */
  it('opens the header menu as the bottom sheet on a phone', async () => {
    const restore = matchMediaQueries(MEDIA.phone);
    try {
      const { fixture } = await setup({ variant: 'header' });
      await userEvent.click(trigger());
      fixture.detectChanges();
      expect(trigger()).toHaveAttribute('aria-expanded', 'true');
      expect(panel()).toBeNull();
      expect(screen.getByRole('dialog', { name: 'Hilfe' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /Handbuch im Wiki/ })).toHaveAttribute('href', WIKI);
    } finally {
      restore();
    }
  });

  /** §000593 the group "Darstellung" with its five switches, with and without a login. */
  it('shows the display switches in the order of the spec, also for a visitor', async () => {
    await setup({ variant: 'sheet', menu: 'a11y', signedIn: false });
    const group = screen.getByRole('group', { name: 'Barrierefreiheit' });
    expect(screen.queryByText('Darstellung')).toBeNull();
    const names = Array.from(group.querySelectorAll('[role="switch"]')).map((s) =>
      document.getElementById(s.getAttribute('aria-labelledby')!)!.textContent!.trim(),
    );
    expect(names).toEqual([
      'Dunkles Design',
      'Weniger Bewegung',
      'Weniger Transparenz',
      'Mehr Kontrast',
      'Hoher Kontrast',
    ]);
  });

  /** §000606 very high contrast turns the other switches on and disables them. */
  it('locks the other switches on while very high contrast is on', async () => {
    const { fixture } = await setup({ variant: 'sheet', menu: 'a11y' });
    const display = fixture.debugElement.injector.get(DisplaySettingsService);
    display.reset();
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('switch', { name: 'Hoher Kontrast' }));
    fixture.detectChanges();
    for (const name of [
      'Dunkles Design',
      'Mehr Kontrast',
      'Weniger Bewegung',
      'Weniger Transparenz',
    ]) {
      const toggle = screen.getByRole('switch', { name });
      expect(toggle).toHaveAttribute('aria-checked', 'true');
      expect(toggle).toBeDisabled();
    }
    expect(screen.getByRole('switch', { name: 'Hoher Kontrast' })).toBeEnabled();
    expect(document.documentElement.getAttribute('data-fields')).toBe('highlight');
    display.reset();
  });

  /** §000594 a switch shows the state in effect and overrides the system; the reset clears all. */
  it('sets a display setting and the theme, and resets both to the system', async () => {
    const { fixture } = await setup({ variant: 'sheet', menu: 'a11y' });
    const display = fixture.debugElement.injector.get(DisplaySettingsService);
    const theme = fixture.debugElement.injector.get(ThemeService);
    display.reset();
    theme.setPreference('system');
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Systemeinstellungen verwenden' })).toBeNull();

    const transparency = screen.getByRole('switch', { name: 'Weniger Transparenz' });
    expect(transparency).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(transparency);
    expect(display.effective().transparency).toBe(true);
    expect(document.documentElement.getAttribute('data-transparency')).toBe('reduce');
    expect(transparency).toHaveAttribute('aria-checked', 'true');

    await userEvent.click(screen.getByRole('switch', { name: 'Dunkles Design' }));
    expect(theme.preference()).toBe('dark');
    expect(screen.getByRole('switch', { name: 'Dunkles Design' })).toHaveAttribute('aria-checked', 'true');

    await userEvent.click(screen.getByRole('button', { name: 'Systemeinstellungen verwenden' }));
    expect(display.hasChoice()).toBe(false);
    expect(theme.preference()).toBe('system');
    expect(screen.queryByRole('button', { name: 'Systemeinstellungen verwenden' })).toBeNull();
  });

  it('offers the reset while only the theme is set', async () => {
    const { fixture } = await setup({ variant: 'sheet', menu: 'a11y' });
    fixture.debugElement.injector.get(DisplaySettingsService).reset();
    fixture.debugElement.injector.get(ThemeService).setPreference('light');
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Systemeinstellungen verwenden' })).toBeInTheDocument();
    fixture.debugElement.injector.get(ThemeService).setPreference('system');
  });
});
