import { TestBed } from '@angular/core/testing';
import { FEATURES, FeatureService, offFeatures } from './feature.service';

/** Specs 000756 and 000758: the UI reads the state of each feature from the site config. */
describe('FeatureService', () => {
  afterEach(() => localStorage.clear());

  const service = () => TestBed.inject(FeatureService);

  it('has every feature on before a config names a state', () => {
    expect(service().isOn(...FEATURES)).toBe(true);
    expect(service().off().size).toBe(0);
  });

  it('takes the states of the config and keeps them for the next start', () => {
    const features = service();
    features.apply({ todos: false, invoices: false });
    expect(features.isOn('todos')).toBe(false);
    expect(features.isOn('budget')).toBe(true);
    expect(features.isOn('budget', 'invoices')).toBe(false);
    expect(features.states().todos).toBe(false);
    expect(features.states().calendar).toBe(true);
    expect(JSON.parse(localStorage.getItem('ap.features.off') ?? '[]')).toEqual([
      'todos',
      'invoices',
    ]);
  });

  it('starts with the states that the browser kept', () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['tickets', 'unknown']));
    expect(service().isOn('tickets')).toBe(false);
    expect(service().off().size).toBe(1);
  });

  it('ignores a kept value that is not a list', () => {
    localStorage.setItem('ap.features.off', '{broken');
    expect(service().isOn(...FEATURES)).toBe(true);
  });

  it('resolves `ready` after the config and after a failed load', async () => {
    const loaded = service();
    loaded.apply(null);
    await expect(loaded.ready).resolves.toBeUndefined();
    TestBed.resetTestingModule();
    const failed = service();
    failed.loadFailed();
    await expect(failed.ready).resolves.toBeUndefined();
  });

  it('names a version for the config load only after a save in this browser', () => {
    const features = service();
    expect(features.configVersion()).toBeNull();
    features.saved({ calendar: false });
    expect(features.configVersion()).toMatch(/^\d+$/);
    expect(features.isOn('calendar')).toBe(false);
  });
});

describe('offFeatures', () => {
  it('reads a feature without an entry as on', () => {
    expect(offFeatures(null)).toEqual([]);
    expect(offFeatures({ voting: false, budget: true })).toEqual(['voting']);
  });
});
