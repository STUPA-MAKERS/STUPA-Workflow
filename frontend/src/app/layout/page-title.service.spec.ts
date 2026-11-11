import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Title } from '@angular/platform-browser';
import { type Route, Router, TitleStrategy, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { BrandingService } from '@core/branding/branding.service';
import de from '@core/i18n/catalog/de.json';
import en from '@core/i18n/catalog/en.json';
import { I18nService } from '@core/i18n/i18n.service';
import { routes } from '../app.routes';
import { PageFrameService } from './page-frame.service';
import { PageTitleService, pageItemTitle } from './page-title.service';

/** A detail page that names its item once the item "loaded". */
@Component({ standalone: true, template: '<h1>{{ name() }}</h1>' })
class DetailPage {
  static readonly itemName = signal<string | null>(null);
  readonly name = DetailPage.itemName;
  constructor() {
    pageItemTitle(() => this.name());
  }
}

@Component({ standalone: true, template: '<h1>Seite</h1>' })
class PlainPage {}

describe('PageTitleService', () => {
  let harness: RouterTestingHarness;
  let title: Title;
  let app: string;

  beforeEach(async () => {
    DetailPage.itemName.set(null);
    TestBed.configureTestingModule({
      providers: [
        provideRouter([
          { path: 'tickets', component: PlainPage, data: { title: 'nav.tickets' } },
          { path: 'tickets/:id', component: DetailPage, data: { title: 'nav.tickets' } },
          {
            path: 'admin',
            data: { title: 'nav.admin' },
            children: [
              { path: 'users', component: PlainPage, data: { title: 'admin.users.title' } },
              { path: 'plain', component: PlainPage },
            ],
          },
          { path: 'untitled', component: PlainPage },
          { path: 'committees/:id', component: PlainPage, data: { title: 'nav.gremien' } },
        ]),
        { provide: TitleStrategy, useExisting: PageTitleService },
      ],
    });
    harness = await RouterTestingHarness.create();
    title = TestBed.inject(Title);
    app = TestBed.inject(BrandingService).appName();
  });

  const tr = (key: Parameters<I18nService['translate']>[0]): string =>
    TestBed.inject(I18nService).translate(key);

  const current = (): string => {
    TestBed.tick();
    return title.getTitle();
  };

  it('puts the route title before the app name', async () => {
    await harness.navigateByUrl('/tickets');
    expect(current()).toBe(`${tr('nav.tickets')} – ${app}`);
  });

  it('takes the deepest route with a title, and the parent for a child without one', async () => {
    await harness.navigateByUrl('/admin/users');
    expect(current()).toBe(`${tr('admin.users.title')} – ${app}`);
    await harness.navigateByUrl('/admin/plain');
    expect(current()).toBe(`${tr('nav.admin')} – ${app}`);
  });

  it('shows the app name alone on a page without a title', async () => {
    await harness.navigateByUrl('/untitled');
    expect(current()).toBe(app);
  });

  it('names the item of a detail page once it loaded, and only on its URL', async () => {
    await harness.navigateByUrl('/tickets/1');
    expect(current()).toBe(`${tr('nav.tickets')} – ${app}`);
    DetailPage.itemName.set('  Drucker kaputt ');
    expect(current()).toBe(`Drucker kaputt – ${app}`);
    DetailPage.itemName.set(null);
    await harness.navigateByUrl('/tickets/2?tab=notes');
    expect(current()).toBe(`${tr('nav.tickets')} – ${app}`);
    DetailPage.itemName.set('Beamer');
    expect(current()).toBe(`Beamer – ${app}`);
    await harness.navigateByUrl('/tickets');
    expect(current()).toBe(`${tr('nav.tickets')} – ${app}`);
  });

  it('takes the breadcrumb label of a page for its URL', async () => {
    const frame = TestBed.inject(PageFrameService);
    await harness.navigateByUrl('/committees/7');
    frame.crumbLabel.set({ url: '/committees/7', label: 'StuPa' });
    expect(current()).toBe(`StuPa – ${app}`);
    frame.crumbLabel.set({ url: '/committees/8', label: 'AStA' });
    expect(current()).toBe(`${tr('nav.gremien')} – ${app}`);
  });

  it('follows the language and the configured app name', async () => {
    await harness.navigateByUrl('/tickets');
    TestBed.inject(I18nService).setLocale('en');
    expect(current()).toBe(`${tr('nav.tickets')} – ${TestBed.inject(BrandingService).appName()}`);
    expect(TestBed.inject(Router).url).toBe('/tickets');
  });

  it('leaves a name that another page set', () => {
    const titles = TestBed.inject(PageTitleService);
    const mine = {};
    titles.setItem({}, 'Fremd');
    titles.setItem(mine, null);
    expect(titles.page()).toBe('Fremd');
  });
});

/** Every `data.title` key of a route tree. */
function titleKeys(tree: readonly Route[]): string[] {
  return tree.flatMap((r) => {
    const own = typeof r.data?.['title'] === 'string' ? [r.data['title'] as string] : [];
    return [...own, ...titleKeys(r.children ?? [])];
  });
}

/** The router fills no placeholder: a route title with `{name}` shows the braces in the tab. */
describe('route titles', () => {
  it('are texts without a placeholder in every catalog', () => {
    const catalogs: readonly Record<string, string>[] = [de, en];
    const keys = [...new Set(titleKeys(routes))];
    expect(keys.length).toBeGreaterThan(20);
    const bad = keys.filter((k) => catalogs.some((c) => !(k in c) || /\{\w+\}/.test(c[k])));
    expect(bad).toEqual([]);
  });
});
