import { TestBed } from '@angular/core/testing';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { PageIndexService } from './page-index.service';

/**
 * The pages half of the palette must never offer somewhere the user cannot go: a row
 * that bounces to /forbidden is worse than no row. The filter mirrors `authGuard`, so
 * these tests pin that mirror, including the three escape hatches it has.
 */
describe('PageIndexService', () => {
  function setup(auth: Partial<Record<string, unknown>>) {
    TestBed.configureTestingModule({
      providers: [
        {
          provide: AuthService,
          useValue: {
            isAuthenticated: () => true,
            canAny: () => false,
            gremien: () => [],
            hasScopedBudgetView: () => false,
            ...auth,
          },
        },
        // Translate to the key, so a test asserts on routes and not on wording.
        { provide: I18nService, useValue: { translate: (k: string) => k } },
      ],
    });
    return TestBed.inject(PageIndexService);
  }

  it('offers nothing to a caller who is not signed in', () => {
    const svc = setup({ isAuthenticated: () => false });
    expect(svc.visible()).toEqual([]);
  });

  it('offers a page whose permission the caller holds', () => {
    const svc = setup({ canAny: (...p: string[]) => p.includes('admin.roles') });
    expect(svc.visible().map((e) => e.path)).toContain('/admin/roles');
  });

  it('withholds a page whose permission the caller lacks', () => {
    const svc = setup({});
    expect(svc.visible().map((e) => e.path)).not.toContain('/admin/roles');
  });

  it('skips record routes, which the record half of the search already covers', () => {
    const svc = setup({ canAny: () => true });
    expect(svc.visible().every((e) => !e.path.includes(':'))).toBe(true);
  });

  it('lets a committee member through on a route that allows it', () => {
    // `/meetings` carries allowCommitteeMember: a member sees the meetings of their
    // gremium without meeting.manage. The guard does the same.
    const svc = setup({ gremien: () => [{ id: 'g-1' }] });
    expect(svc.visible().map((e) => e.path)).toContain('/meetings');
  });

  it('lets a scoped budget viewer through on a route that allows it', () => {
    const svc = setup({ hasScopedBudgetView: () => true });
    expect(svc.visible().map((e) => e.path)).toContain('/budget');
  });

  it('resolves the label through i18n rather than showing a raw key', () => {
    const svc = setup({ canAny: () => true });
    const entry = svc.visible().find((e) => e.path === '/admin/roles');
    expect(entry?.label).toBe('admin.roles.title');
  });
});
