import { TestBed } from '@angular/core/testing';
import { I18nService } from '@core/i18n/i18n.service';
import { createLocationMock, provideLocationMock } from '../../testing/location-mock';
import { LocaleSwitchService } from './locale-switch.service';

describe('LocaleSwitchService', () => {
  function setup() {
    localStorage.setItem('ap.locale', 'de');
    const location = createLocationMock();
    TestBed.configureTestingModule({ providers: [provideLocationMock(location)] });
    return { svc: TestBed.inject(LocaleSwitchService), i18n: TestBed.inject(I18nService), location };
  }

  afterEach(() => localStorage.clear());

  it('sets the new language and reloads the view', () => {
    const { svc, i18n, location } = setup();
    svc.switchTo('en');
    expect(i18n.locale()).toBe('en');
    expect(location.reload).toHaveBeenCalledTimes(1);
  });

  it('does nothing for the current language or an unknown one', () => {
    const { svc, i18n, location } = setup();
    svc.switchTo('de');
    svc.switchTo('fr');
    expect(i18n.locale()).toBe('de');
    expect(location.reload).not.toHaveBeenCalled();
  });
});
