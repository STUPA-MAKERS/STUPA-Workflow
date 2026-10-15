import { signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { HelpService } from '../help.service';
import { HelpMenuComponent, type HelpMenuVariant } from './help-menu.component';

const WIKI = 'https://wiki.example.org/books/stupa';

async function setup(opts: { variant?: HelpMenuVariant; signedIn?: boolean; publicTickets?: boolean } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const navigated = jest.fn();
  const view = await render(HelpMenuComponent, {
    inputs: { variant: opts.variant ?? 'rail' },
    on: { navigated },
    providers: [
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
    // The second line shows the address without the scheme.
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
    // Escape on a closed menu does nothing.
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  });

  it('closes on a press or a focus outside and on a resize, not on one inside', async () => {
    const { fixture } = await setup();
    const outside = document.createElement('button');
    document.body.appendChild(outside);

    // Nothing to close yet.
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
});
