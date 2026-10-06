import { Component, signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Principal } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { CommandPaletteService } from '../../features/search/command-palette.service';
import { RailStatusService } from '../rail-status.service';
import { createLocationMock, provideLocationMock } from '../../../testing/location-mock';
import { BottomBarComponent } from './bottom-bar.component';

@Component({ standalone: true, template: 'page' })
class StubPage {}

const ADMIN: Principal = {
  sub: '1',
  display_name: 'Ada Admin',
  email: 'ada@stupa',
  roles: ['admin'],
  permissions: [],
  groups: [],
};

const MEMBER: Principal = { ...ADMIN, display_name: 'Mia Member', roles: ['member'] };

async function setup(principal: Principal = ADMIN) {
  localStorage.setItem('ap.locale', 'de');
  const view = await render(BottomBarComponent, {
    providers: [
      provideRouter([
        { path: 'dashboard', component: StubPage },
        { path: 'budget', component: StubPage },
        { path: 'account/notifications', component: StubPage },
        { path: 'expenses', component: StubPage },
      ]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      provideLocationMock(createLocationMock()),
      {
        provide: RailStatusService,
        useValue: { taskCount: signal(8), live: signal(true), refresh: () => undefined },
      },
    ],
  });
  const injector = view.fixture.debugElement.injector;
  injector.get(AuthService).ensureLoaded().subscribe();
  injector.get(HttpTestingController).expectOne('/api/auth/me').flush(principal);
  view.fixture.detectChanges();
  return { ...view, router: injector.get(Router), palette: injector.get(CommandPaletteService) };
}

const bar = () => screen.getByRole('navigation', { name: 'Hauptnavigation' });
const more = () => within(bar()).getByRole('button', { name: 'Mehr' });

describe('BottomBarComponent', () => {
  afterEach(() => localStorage.clear());

  it('shows Start, Anträge, Sitzungen and Aufgaben, then Mehr', async () => {
    await setup();
    const labels = Array.from(bar().querySelectorAll('.bb__label')).map((l) => l.textContent?.trim());
    expect(labels).toEqual(['Start', 'Anträge', 'Sitzungen', 'Aufgaben', 'Mehr']);
    expect(within(bar()).getByRole('link', { name: 'Aufgaben 8 offen' })).toHaveAttribute('href', '/tasks');
    expect(within(bar()).getByRole('link', { name: 'Sitzungen Sitzung läuft' })).toBeInTheDocument();
  });

  it('leaves out Sitzungen for a principal who cannot see meetings', async () => {
    await setup(MEMBER);
    expect(within(bar()).queryByRole('link', { name: /^Sitzungen/ })).not.toBeInTheDocument();
  });

  it('lists the other areas, the search and the account in the Mehr sheet', async () => {
    const { fixture } = await setup();
    expect(more()).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(more());
    fixture.detectChanges();

    const sheet = screen.getByRole('dialog', { name: 'Mehr' });
    for (const name of ['Abstimmungen', 'Budget', 'Buchungen', 'Rechnungen', 'Verwaltung']) {
      expect(within(sheet).getByRole('link', { name })).toBeInTheDocument();
    }
    // The bar entries are not repeated in the sheet.
    expect(within(sheet).queryByRole('link', { name: 'Start' })).not.toBeInTheDocument();
    expect(within(sheet).getByRole('button', { name: 'Suche' })).toBeInTheDocument();
    expect(within(sheet).getByText('Ada Admin')).toBeInTheDocument();
    expect(within(sheet).getByRole('button', { name: 'Abmelden' })).toBeInTheDocument();
  });

  it('opens the search palette from the sheet and closes the sheet', async () => {
    const { fixture, palette } = await setup();
    await userEvent.click(more());
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Suche' }));
    fixture.detectChanges();
    expect(palette.isOpen()).toBe(true);
    expect(screen.queryByRole('dialog', { name: 'Mehr' })).not.toBeInTheDocument();
  });

  it('closes the sheet when a link in it is followed', async () => {
    const { fixture } = await setup();
    await userEvent.click(more());
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('link', { name: 'Budget' }));
    fixture.detectChanges();
    expect(screen.queryByRole('dialog', { name: 'Mehr' })).not.toBeInTheDocument();
  });

  it('marks Mehr as active on a page that lives in the sheet', async () => {
    const { fixture, router } = await setup();
    await router.navigateByUrl('/budget');
    fixture.detectChanges();
    expect(more()).toHaveClass('is-active');

    await router.navigateByUrl('/account/notifications');
    fixture.detectChanges();
    expect(more()).toHaveClass('is-active');

    await router.navigateByUrl('/dashboard');
    fixture.detectChanges();
    expect(more()).not.toHaveClass('is-active');
    expect(within(bar()).getByRole('link', { name: 'Start' })).toHaveAttribute('aria-current', 'page');
  });
});
