import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { cacheInterceptor, listContext } from '@core/cache/cache.interceptor';
import { loadingInterceptor, LoadingService } from '@stupa-makers/ui-kit';
import { isRefreshItem, REFRESH_MENU_ID, refreshMenuSection, reloadLikePull } from './refresh-menu';

describe('refreshMenuSection', () => {
  it('offers one "Aktualisieren" entry that isRefreshItem knows', () => {
    const section = refreshMenuSection((key) => `t:${key}`);
    expect(section.items).toEqual([{ id: REFRESH_MENU_ID, label: 't:action.refresh', icon: 'reload' }]);
    expect(isRefreshItem(section.items[0])).toBe(true);
    expect(isRefreshItem({ id: 'export', label: 'Export' })).toBe(false);
  });

  /** The menu entry reloads like a pull: past the HTTP cache, with the bar of the app. */
  it('reloads past the cache and runs the bar of the app', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([loadingInterceptor, cacheInterceptor])), provideHttpClientTesting()],
    });
    const http = TestBed.inject(HttpClient);
    const ctl = TestBed.inject(HttpTestingController);
    const loading = TestBed.inject(LoadingService);
    const get = () => http.get('/api/applications', { context: listContext(0) }).subscribe();
    get();
    ctl.expectOne('/api/applications').flush([1]);
    reloadLikePull(get);
    expect(loading.active()).toBe(true);
    ctl.expectOne('/api/applications').flush([2]);
    ctl.verify();
  });
});
