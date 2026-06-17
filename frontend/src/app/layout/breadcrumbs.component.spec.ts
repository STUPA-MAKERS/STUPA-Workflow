import { Component } from '@angular/core';
import { Router, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { BreadcrumbsComponent } from './breadcrumbs.component';
import { I18nService } from '@core/i18n/i18n.service';

@Component({ standalone: true, template: 'page' })
class StubPage {}

/** Routes carrying title/parent data the breadcrumbs read. */
const routes = [
  // Flat sibling whose parent must be resolved from the config by path.
  {
    path: 'budget',
    component: StubPage,
    data: { title: 'nav.budget' as const },
  },
  {
    path: 'budget/pots',
    component: StubPage,
    data: { title: 'nav.expenses' as const, parent: ['budget'] },
  },
  // Leaf with a parent path that has NO title in the config (skipped).
  {
    path: 'orphan',
    component: StubPage,
    data: { title: 'nav.tasks' as const, parent: ['does/not/exist'] },
  },
  // Leaf with title but no declared parent → single crumb, nav not rendered.
  {
    path: 'solo',
    component: StubPage,
    data: { title: 'nav.dashboard' as const },
  },
  // Route without any title data at all → no crumbs.
  { path: 'untitled', component: StubPage },
  // Nested children to exercise the recursive config walk + title-by-path map.
  {
    path: 'admin',
    data: { title: 'nav.admin' as const },
    children: [
      {
        path: 'users',
        component: StubPage,
        data: { title: 'nav.applications' as const, parent: ['admin'] },
      },
    ],
  },
];

async function setup() {
  const view = await render(BreadcrumbsComponent, {
    providers: [provideRouter(routes)],
  });
  const router = view.fixture.debugElement.injector.get(Router);
  const i18n = view.fixture.debugElement.injector.get(I18nService);
  return { ...view, router, i18n };
}

describe('BreadcrumbsComponent', () => {
  it('renders nothing when there is no titled route', async () => {
    const { router, fixture } = await setup();
    await router.navigateByUrl('/untitled');
    fixture.detectChanges();
    expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).not.toBeInTheDocument();
  });

  it('renders nothing when the current page has no parent (single crumb)', async () => {
    const { router, fixture } = await setup();
    await router.navigateByUrl('/solo');
    fixture.detectChanges();
    // Only one crumb → the H1 suffices, nav is hidden.
    expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).not.toBeInTheDocument();
  });

  it('prepends a config-resolved parent crumb before the current page', async () => {
    const { router, fixture, i18n } = await setup();
    await router.navigateByUrl('/budget/pots');
    fixture.detectChanges();

    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toBeInTheDocument();
    // Parent crumb is a link to /budget …
    const parent = screen.getByRole('link', { name: i18n.translate('nav.budget') });
    expect(parent).toHaveAttribute('href', '/budget');
    // … and the current page is the aria-current span (not a link).
    const current = screen.getByText(i18n.translate('nav.expenses'));
    expect(current).toHaveAttribute('aria-current', 'page');
  });

  it('skips parent paths that are not declared in the route config', async () => {
    const { router, fixture, i18n } = await setup();
    await router.navigateByUrl('/orphan');
    fixture.detectChanges();
    // Parent path "does/not/exist" has no title → no parent crumb → only one crumb → nav hidden.
    expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: i18n.translate('nav.tasks') })).not.toBeInTheDocument();
  });

  it('resolves a parent declared on a nested (child) route via the recursive walk', async () => {
    const { router, fixture, i18n } = await setup();
    await router.navigateByUrl('/admin/users');
    fixture.detectChanges();
    expect(screen.getByRole('link', { name: i18n.translate('nav.admin') })).toHaveAttribute(
      'href',
      '/admin',
    );
    expect(screen.getByText(i18n.translate('nav.applications'))).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('refreshes the crumbs on every navigation', async () => {
    const { router, fixture, i18n } = await setup();
    await router.navigateByUrl('/budget/pots');
    fixture.detectChanges();
    expect(screen.getByText(i18n.translate('nav.expenses'))).toBeInTheDocument();

    await router.navigateByUrl('/untitled');
    fixture.detectChanges();
    expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).not.toBeInTheDocument();

    await router.navigateByUrl('/admin/users');
    fixture.detectChanges();
    expect(screen.getByText(i18n.translate('nav.applications'))).toBeInTheDocument();
  });
});
