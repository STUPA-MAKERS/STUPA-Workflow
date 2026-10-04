import { signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Principal } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { createLocationMock, provideLocationMock } from '../../../testing/location-mock';
import { CommandPaletteService } from '../../features/search/command-palette.service';
import { RailStatusService } from '../rail-status.service';
import { NavRailComponent } from './nav-rail.component';

const ADMIN: Principal = {
  sub: '1',
  display_name: 'Ada Admin',
  email: 'ada@stupa',
  roles: ['admin'],
  permissions: [],
  groups: [],
};

async function setup(tasks: number | null = 120) {
  localStorage.setItem('ap.locale', 'de');
  const view = await render(NavRailComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      provideLocationMock(createLocationMock()),
      { provide: BrandingService, useValue: { appName: signal('Antragsplattform') } },
      { provide: RailStatusService, useValue: { taskCount: signal(tasks), live: signal(false) } },
    ],
  });
  const injector = view.fixture.debugElement.injector;
  injector.get(AuthService).ensureLoaded().subscribe();
  injector.get(HttpTestingController).expectOne('/api/auth/me').flush(ADMIN);
  view.fixture.detectChanges();
  return view;
}

describe('NavRailComponent', () => {
  afterEach(() => localStorage.clear());

  it('names the brand mark after the app and links it to the start page', async () => {
    await setup();
    expect(screen.getByRole('link', { name: 'Antragsplattform, Start' })).toHaveAttribute('href', '/dashboard');
  });

  it('caps the task badge at 99+ but says the full count', async () => {
    const { container } = await setup(120);
    expect(container.querySelector('.mark__count')).toHaveTextContent('99+');
    expect(screen.getByRole('link', { name: 'Aufgaben 120 offen' })).toBeInTheDocument();
  });

  it('puts Verwaltung and the account at the foot of the rail, after the spacer', async () => {
    const { container } = await setup();
    const nav = container.querySelector('nav.rail') as HTMLElement;
    const children = Array.from(nav.children).map((c) => c.className.split(' ')[0] || c.tagName.toLowerCase());
    const spacer = children.indexOf('rail__spacer');
    expect(spacer).toBeGreaterThan(0);
    expect(children.slice(spacer + 1)).toEqual(['rail__item', 'rail__account']);
    expect(within(nav).getByRole('button', { name: 'Konto: Ada Admin' })).toBeInTheDocument();
  });

  it('opens the search palette from every page, with the shortcut named', async () => {
    const view = await setup();
    const palette = view.fixture.debugElement.injector.get(CommandPaletteService);
    const button = screen.getByRole('button', { name: 'Suche' });
    expect(button).toHaveAttribute('aria-keyshortcuts', expect.stringMatching(/^(Control|Meta)\+K$/));
    expect(palette.isOpen()).toBe(false);
    button.click();
    expect(palette.isOpen()).toBe(true);
    palette.close();
  });

  it('shows no badge before the first answer', async () => {
    const { container } = await setup(null);
    expect(container.querySelector('.mark__count')).toBeNull();
    expect(screen.getByRole('link', { name: 'Aufgaben' })).toBeInTheDocument();
  });
});
