import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { BrandingService } from '@core/branding/branding.service';
import { AvatarService } from './avatar.service';

function setup(loaded = true, enabled = true) {
  const branding = { loaded: signal(loaded), gravatarEnabled: signal(enabled) };
  TestBed.configureTestingModule({
    providers: [{ provide: BrandingService, useValue: branding }],
  });
  return { svc: TestBed.inject(AvatarService), branding };
}

describe('AvatarService', () => {
  it('builds the proxy URL at twice the size', () => {
    const { svc } = setup();
    expect(svc.url('8c3f', 32)).toBe('/api/principals/8c3f/avatar?s=64');
    expect(svc.url('me', 40)).toBe('/api/principals/me/avatar?s=80');
    expect(svc.url('a/b c', 40)).toBe('/api/principals/a%2Fb%20c/avatar?s=80');
  });

  it('gives no URL without a principal', () => {
    const { svc } = setup();
    expect(svc.url(null, 40)).toBeNull();
    expect(svc.url(undefined, 40)).toBeNull();
    expect(svc.url('', 40)).toBeNull();
  });

  it('waits for the site config and follows the admin switch', () => {
    const { svc, branding } = setup(false, true);
    expect(svc.enabled()).toBe(false);
    expect(svc.url('p1', 40)).toBeNull();
    branding.loaded.set(true);
    expect(svc.url('p1', 40)).not.toBeNull();
    branding.gravatarEnabled.set(false);
    expect(svc.enabled()).toBe(false);
    expect(svc.url('p1', 40)).toBeNull();
  });

  it('remembers a failed principal for the session', () => {
    const { svc } = setup();
    svc.markFailed('p1');
    svc.markFailed('p1');
    expect(svc.url('p1', 40)).toBeNull();
    expect(svc.url('p2', 40)).not.toBeNull();
  });
});
