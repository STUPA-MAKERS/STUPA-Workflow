import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { SwPush } from '@angular/service-worker';
import { IS_INSTALLED_APP } from '@stupa-makers/ui-kit/pwa';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { PushDevice } from '@core/api/models';
import { PushDeviceService, deviceLabel, isAppleMobile } from './push-device.service';

const IPHONE =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1';
const CHROME_WIN =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36';
const EDGE_MAC =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36 Edg/131.0';

const DEVICE: PushDevice = {
  id: 'd1',
  label: 'Chrome · Windows',
  endpoint: 'https://fcm.googleapis.com/x',
  createdAt: '2026-11-22T10:00:00Z',
  lastSuccessAt: null,
};

interface WinOpts {
  push?: boolean;
  permission?: NotificationPermission;
  userAgent?: string;
  platform?: string;
  touch?: number;
}

function fakeWindow(o: WinOpts = {}) {
  const nav = {
    userAgent: o.userAgent ?? CHROME_WIN,
    platform: o.platform ?? 'Win32',
    maxTouchPoints: o.touch ?? 0,
  };
  return o.push === false
    ? { navigator: nav }
    : { navigator: nav, PushManager: {}, Notification: { permission: o.permission ?? 'default' } };
}

function setup(
  o: WinOpts & { sw?: boolean | null; installed?: boolean; subscription?: object | null } = {},
) {
  const sub = {
    endpoint: DEVICE.endpoint,
    toJSON: () => ({ keys: { p256dh: 'P', auth: 'A' } }),
  };
  const swPush =
    o.sw === null
      ? null
      : {
          isEnabled: o.sw ?? true,
          subscription: of(o.subscription === undefined ? sub : o.subscription),
          requestSubscription: jest.fn(() => Promise.resolve(sub)),
          unsubscribe: jest.fn(() => Promise.resolve()),
        };
  const api = {
    getPushKey: jest.fn(() => of({ publicKey: 'KEY' })),
    addPushDevice: jest.fn(() => of(DEVICE)),
    removePushDevice: jest.fn(() => of(undefined)),
  };
  TestBed.configureTestingModule({
    providers: [
      { provide: DOCUMENT, useValue: { defaultView: fakeWindow(o) } },
      { provide: ApiClient, useValue: api },
      { provide: IS_INSTALLED_APP, useValue: () => o.installed ?? false },
      ...(swPush ? [{ provide: SwPush, useValue: swPush }] : []),
    ],
  });
  return { service: TestBed.inject(PushDeviceService), swPush, api };
}

describe('isAppleMobile', () => {
  it('knows an iPhone and an iPad that reports itself as a Mac', () => {
    expect(
      isAppleMobile({ userAgent: IPHONE, platform: 'iPhone', maxTouchPoints: 5 } as Navigator),
    ).toBe(true);
    expect(
      isAppleMobile({ userAgent: EDGE_MAC, platform: 'MacIntel', maxTouchPoints: 5 } as Navigator),
    ).toBe(true);
    expect(
      isAppleMobile({ userAgent: EDGE_MAC, platform: 'MacIntel', maxTouchPoints: 0 } as Navigator),
    ).toBe(false);
  });
});

describe('deviceLabel', () => {
  it('names the browser and the system', () => {
    expect(deviceLabel(IPHONE)).toBe('Safari · iPhone');
    expect(deviceLabel(CHROME_WIN)).toBe('Chrome · Windows');
    expect(deviceLabel(EDGE_MAC)).toBe('Edge · Mac');
    expect(deviceLabel('curl/8')).toBe('');
  });
});

describe('PushDeviceService', () => {
  it('is ready with push and a running service worker', () => {
    expect(setup().service.support()).toBe('ready');
  });

  it('is blocked when the person blocked notifications', () => {
    expect(setup({ permission: 'denied' }).service.support()).toBe('blocked');
  });

  it('asks for the install on an iPhone without the app on the home screen', () => {
    expect(setup({ push: false, userAgent: IPHONE, platform: 'iPhone' }).service.support()).toBe(
      'install',
    );
  });

  it('is unsupported without push, and without a service worker', () => {
    expect(setup({ push: false }).service.support()).toBe('unsupported');
    TestBed.resetTestingModule();
    expect(setup({ sw: false }).service.support()).toBe('unsupported');
    TestBed.resetTestingModule();
    expect(
      setup({
        push: false,
        userAgent: IPHONE,
        platform: 'iPhone',
        installed: true,
      }).service.support(),
    ).toBe('unsupported');
  });

  it('reads the endpoint of the subscription, or null', async () => {
    expect(await setup().service.endpoint()).toBe(DEVICE.endpoint);
    TestBed.resetTestingModule();
    expect(await setup({ subscription: null }).service.endpoint()).toBeNull();
    TestBed.resetTestingModule();
    expect(await setup({ sw: null }).service.endpoint()).toBeNull();
  });

  it('subscribes with the key of the platform and stores the device', async () => {
    const { service, swPush, api } = setup();
    expect(await service.enable()).toEqual(DEVICE);
    expect(swPush?.requestSubscription).toHaveBeenCalledWith({ serverPublicKey: 'KEY' });
    expect(api.addPushDevice).toHaveBeenCalledWith({
      endpoint: DEVICE.endpoint,
      keys: { p256dh: 'P', auth: 'A' },
      label: 'Chrome · Windows',
    });
  });

  it('refuses to subscribe without a service worker', async () => {
    await expect(setup({ sw: false }).service.enable()).rejects.toThrow('push unavailable');
  });

  it('removes the row and unsubscribes', async () => {
    const { service, swPush, api } = setup();
    await service.disable(DEVICE);
    expect(api.removePushDevice).toHaveBeenCalledWith('d1');
    expect(swPush?.unsubscribe).toHaveBeenCalled();
  });

  it('unsubscribes without a row, and does nothing without a service worker', async () => {
    const { service, swPush, api } = setup();
    swPush?.unsubscribe.mockReturnValue(Promise.reject(new Error('none')));
    await service.disable(undefined);
    expect(api.removePushDevice).not.toHaveBeenCalled();
    TestBed.resetTestingModule();
    await expect(setup({ sw: null }).service.disable(undefined)).resolves.toBeUndefined();
  });
});
