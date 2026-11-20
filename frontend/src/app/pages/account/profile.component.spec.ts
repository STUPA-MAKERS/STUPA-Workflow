import { of, throwError } from 'rxjs';
import { render, type RenderResult, screen } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import type { Profile } from '@core/api/models';
import { BrandingService } from '@core/branding/branding.service';
import { signal } from '@angular/core';
import { runAxe } from '../../../testing/a11y';
import { AccountProfileComponent, GRAVATAR_PROFILE_URL } from './profile.component';

const PROFILE: Profile = {
  sub: 'u-1',
  email: 'ada@x.de',
  displayName: 'Ada Lovelace',
  lastLogin: '2026-11-16T08:00:00Z',
  claims: [
    { key: 'email_verified', value: true },
    { key: 'groups', value: ['stupa', 'asta'] },
    { key: 'custom_claim', value: { a: 1 } },
    { key: 'updated_at', value: 1_700_000_000 },
  ],
};

async function setup(
  answer = of(PROFILE),
  gravatar = true,
): Promise<RenderResult<AccountProfileComponent>> {
  const api = { getMyProfile: jest.fn(() => answer) };
  const branding = { loaded: signal(true), gravatarEnabled: signal(gravatar) };
  const view = await render(AccountProfileComponent, {
    providers: [
      { provide: ApiClient, useValue: api },
      { provide: BrandingService, useValue: branding },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return view;
}

describe('AccountProfileComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows one row per claim with label and value, and the last login', async () => {
    const { container } = await setup();
    const rows = [...container.querySelectorAll('.pf__row')].map((r) => [
      r.querySelector('.pf__label')?.textContent?.trim(),
      r.querySelector('.pf__value')?.textContent?.trim(),
    ]);
    expect(rows[0]).toEqual(['E-Mail bestätigt', 'Ja']);
    expect(rows[1]).toEqual(['Gruppen', 'stupa, asta']);
    expect(rows[2]).toEqual(['custom_claim', '{"a":1}']);
    expect(rows[3][0]).toBe('Zuletzt geändert');
    expect(rows[3][1]).toContain('2023');
    expect(rows[4][0]).toBe('Letzte Anmeldung');
    expect(screen.getByText('Ada Lovelace')).toBeTruthy();
    expect(screen.getByText('ada@x.de')).toBeTruthy();
  });

  it('formats every kind of claim value and falls back to the e-mail as name', async () => {
    const { container } = await setup(
      of({
        sub: 'u-2',
        email: 'bo@x.de',
        displayName: null,
        lastLogin: null,
        claims: [
          { key: 'sub', value: 'u-2' },
          { key: 'email_verified', value: false },
          { key: 'groups', value: [] },
          { key: 'name', value: 'Bo' },
          { key: 'roles', value: [{ id: 1 }, 'x'] },
          { key: 'level', value: 3 },
        ],
      }),
    );
    const rows = [...container.querySelectorAll('.pf__row')].map((r) => [
      r.querySelector('.pf__label')?.textContent?.trim(),
      r.querySelector('.pf__value')?.textContent?.trim(),
    ]);
    expect(rows).toEqual([
      ['Name', 'Bo'],
      ['E-Mail bestätigt', 'Nein'],
      ['Gruppen', '—'],
      ['level', '3'],
      ['roles', '{"id":1}, x'],
      ['Kennung', 'u-2'],
    ]);
    expect(container.querySelector('.pf__name')?.textContent?.trim()).toBe('bo@x.de');
    expect(container.querySelector('.pf__mail')).toBeNull();
  });

  it('shows a dash as name without a name and an e-mail address', async () => {
    const { container } = await setup(
      of({ sub: 'u-3', email: null, displayName: null, lastLogin: null, claims: [] }),
    );
    expect(container.querySelector('.pf__name')?.textContent?.trim()).toBe('—');
  });

  it('links the avatar to the Gravatar profile in a new tab', async () => {
    const { container } = await setup();
    const link = container.querySelector<HTMLAnchorElement>('a.pf__avatar');
    expect(link?.getAttribute('href')).toBe(GRAVATAR_PROFILE_URL);
    expect(link?.target).toBe('_blank');
    expect(link?.rel).toContain('noopener');
    expect(container.querySelector('.pf__ext')).not.toBeNull();
  });

  it('has no link when the admin switched Gravatar off', async () => {
    const { container } = await setup(of(PROFILE), false);
    expect(container.querySelector('a.pf__avatar')).toBeNull();
    expect(container.querySelector('.pf__ext')).toBeNull();
  });

  it('shows an error when the profile does not load', async () => {
    await setup(throwError(() => new Error('x')));
    expect(screen.getByRole('alert').textContent).toContain('Das Profil konnte nicht geladen werden.');
  });

  it('has no axe violations', async () => {
    const { container } = await setup();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
